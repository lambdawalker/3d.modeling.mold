# /// script
# requires-python = ">=3.11"
# dependencies = ["svgelements==1.9.6", "shapely==2.2.0", "trimesh==5.1.1", "mapbox-earcut==2.1.0", "manifold3d==3.5.4", "scipy>=1.13,<2"]
# ///
"""Generate mold walls and grooved bases for every closed SVG shape in one STL.
All output coordinates and CLI dimensions are millimeters. Run with uv run.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import numpy as np
from shapely.geometry import Polygon, box
from shapely.affinity import scale, translate
from shapely.validation import explain_validity
from svgelements import SVG, Path as SVGPath, Move, Close, Line, Shape
import trimesh
import manifold3d as manifold


def positive(value):
    n = float(value)
    if not math.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError('Must be a finite positive number.')
    return n


def read_paths(filename, path_id=None):
    root = ET.parse(filename).getroot()
    for e in root.iter():
        if e.tag.split('}')[-1] in {'use', 'clipPath', 'mask', 'text', 'image'}:
            raise ValueError('Remove images/text/clips/masks and unlink clones before exporting SVG.')
    svg = SVG.parse(str(filename), reify=True, ppi=96)
    paths = []
    for i, e in enumerate(svg.elements()):
        if not isinstance(e, Shape) or (path_id and e.id != path_id):
            continue
        p = SVGPath(e)
        p.reify()
        paths.append((e.id or f'shape-{i}', p))
    if not paths:
        raise ValueError('No matching shapes found in SVG.')
    return paths


def outline(filename, path_id, width, step):
    """Compatibility helper for a single selected outline."""
    paths = read_paths(filename, path_id)
    if len(paths) != 1:
        raise ValueError('Expected one shape; select --path-id or use batch generation.')
    return polygon_from_path(paths[0][1], width, step)


def polygon_from_path(p, width, step):
    subs = list(p.as_subpaths())
    if len(subs) != 1:
        raise ValueError('Use one closed perimeter without holes or disconnected subpaths.')
    segs = list(subs[0])
    if not segs or not isinstance(segs[-1], Close):
        raise ValueError('Path is open. Close its end nodes in Inkscape; a fill alone is not closure.')
    bounds = p.bbox()
    if not bounds or bounds[2] <= bounds[0]:
        raise ValueError('Outline has zero width.')
    factor = width / (bounds[2] - bounds[0]) if width else 25.4 / 96
    points = []
    for s in segs:
        if isinstance(s, Move):
            points.append((s.end.x, -s.end.y))
            continue
        length = s.length(error=1e-6) * factor
        count = 1 if isinstance(s, (Line, Close)) else max(8, math.ceil(length / step))
        if count > 200000:
            raise ValueError('Curve too dense; increase --curve-step.')
        for i in range(1, count + 1):
            pt = s.point(i / count)
            points.append((pt.x, -pt.y))
    poly = Polygon(points)
    if not poly.is_valid or poly.area <= 0:
        raise ValueError('Invalid/self-crossing outline: ' + explain_validity(poly))
    # Sampling may miss an extremum slightly: enforce the requested final width.
    poly = scale(poly, xfact=factor, yfact=factor, origin=(0, 0))
    x0, y0, x1, y1 = poly.bounds
    if width:
        poly = scale(poly, xfact=width/(x1-x0), yfact=width/(x1-x0), origin=(0, 0))
    x0, y0, x1, y1 = poly.bounds
    return translate(poly, -(x0+x1)/2, -(y0+y1)/2)


def prism(poly, height, z=0):
    if poly.geom_type != 'Polygon' or poly.is_empty or not poly.is_valid:
        raise ValueError('Offset split or collapsed. Simplify tight corners or reduce wall/joint dimensions.')
    poly = poly.simplify(1e-7, preserve_topology=True)
    contours = [np.array(poly.exterior.coords)[:-1]] + [np.array(r.coords)[:-1] for r in poly.interiors]
    solid = manifold.CrossSection(contours, manifold.FillRule.EvenOdd).extrude(height)
    data = solid.to_mesh()
    m = trimesh.Trimesh(vertices=data.vert_properties[:, :3], faces=data.tri_verts, process=True)
    m.apply_translation((0, 0, z))
    return m


def offset(p, d):
    return p.buffer(d, quad_segs=24, join_style='round')


def generate(p, a):
    w, t, c, d, b = a.wall, a.tongue, a.clearance, a.seat_depth, a.base_thickness
    inner = (w-t)/2
    if inner <= c:
        raise ValueError('--wall must exceed --tongue + 2 * --clearance (groove must stay outside casting cavity).')
    if b <= d+a.vertical_clearance:
        raise ValueError('Base thickness must exceed seat depth + vertical clearance to retain a solid floor.')
    outer = offset(p, w)
    # Reject closing narrow concavities: they can trap a casting or break registration.
    for shape in (outer, offset(p, inner), offset(p, inner+t+c)):
        if shape.geom_type != 'Polygon' or len(shape.interiors):
            raise ValueError('Offsets close a narrow gap. Simplify the outline or reduce wall thickness.')
    ring = outer.difference(p)
    tongue = offset(p, inner+t).difference(offset(p, inner))
    groove = offset(p, inner+t+c).difference(offset(p, inner-c))
    x0, y0, x1, y1 = outer.bounds
    footprint = box(x0-a.margin, y0-a.margin, x1+a.margin, y1+a.margin)
    base = trimesh.boolean.difference([
        prism(footprint, b),
        prism(groove, d+a.vertical_clearance+1, b-d-a.vertical_clearance)
    ], engine='manifold')
    wall = trimesh.boolean.union([
        prism(ring, a.depth, b),
        prism(tongue, d+min(0.1, a.depth/2), b-d)
    ], engine='manifold')
    casting = prism(p, a.depth, b)
    for name, mesh in [('base', base), ('wall', wall), ('casting', casting)]:
        if not mesh.is_watertight or not mesh.is_volume or mesh.body_count != 1:
            raise ValueError(f'{name}: geometry is not one closed positive-volume solid.')
    return base, wall, casting


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('svg', type=Path)
    p.add_argument('--path-id', help='Inkscape object ID when SVG contains multiple paths')
    p.add_argument('--width', type=positive, help='Override EACH casting width in mm; default preserves SVG physical dimensions at 96 DPI')
    for flag, default, helptext in [
        ('depth', 6, 'Casting depth above flat base'), ('wall', 3, 'Radial wall thickness'),
        ('base-thickness', 5, 'Total base thickness'), ('margin', 6, 'Base border outside wall'),
        ('tongue', 1.4, 'Width of registration tongue under wall'), ('seat-depth', 1.5, 'Tongue engagement depth'),
        ('clearance', 0.2, 'Horizontal gap on EACH side of tongue'),
        ('vertical-clearance', 0.2, 'Gap beneath tongue; wall shoulder rests on base'),
        ('curve-step', 0.25, 'Curve sampling length target; smaller gives smoother outlines')]:
        p.add_argument('--'+flag, type=positive, default=default, help=helptext+' (mm)')
    p.add_argument('--layout-width', type=positive, default=220, help='Maximum layout width in mm (height grows as needed)')
    p.add_argument('--gap', type=positive, default=5, help='Minimum XY gap between print parts, mm')
    p.add_argument('--out', type=Path, default=Path('mold-output'))
    p.add_argument('--force', action='store_true', help='Replace existing output files')
    return p


def print_orientation(mesh, flip=False):
    m = mesh.copy()
    if flip:
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1,0,0]))
    m.apply_translation(-m.bounds[0])
    return m


def pack_parts(parts, width, gap):
    """Shelf layout; never scale parts. Return meshes plus placement records."""
    packed, placements = [], []
    x = y = row_height = 0.0
    for label, mesh in sorted(parts, key=lambda pair: -pair[1].extents[1]):
        m = print_orientation(mesh)
        if m.extents[0] > width:
            m.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2, [0,0,1]))
            m = print_orientation(m)
        w, h, _ = m.extents
        if w > width + 1e-6:
            raise ValueError(f'{label} cannot fit --layout-width {width}; increase it or reduce shape size.')
        if x and x+w > width:
            x = 0.0
            y += row_height + gap
            row_height = 0.0
        m.apply_translation([x,y,0])
        packed.append(m)
        placements.append(dict(part=label, bounds_mm=m.bounds.tolist()))
        x += w+gap
        row_height = max(row_height,h)
    return packed, placements


def build_batch(a):
    parts, individual, reports = [], [], []
    for index, (name, path) in enumerate(read_paths(a.svg,a.path_id),1):
        try:
            poly = polygon_from_path(path,a.width,a.curve_step)
            base,wall,casting = generate(poly,a)
        except ValueError as exc:
            raise ValueError(f'Shape {name}: {exc}') from exc
        # Stable numeric folders avoid unsafe/duplicate SVG IDs as filenames.
        key = f'{index:02d}'
        wall_print = print_orientation(wall,flip=True)
        parts.extend([(key+'-base',base),(key+'-wall',wall_print)])
        individual.append((key,base,wall_print,print_orientation(casting)))
        reports.append(dict(index=index,svg_id=name,casting_size_mm=casting.extents.tolist(),
                            cavity_volume_ml=casting.volume/1000))
    packed,placements = pack_parts(parts,a.layout_width,a.gap)
    combined = trimesh.util.concatenate(packed)
    if not combined.is_watertight or not combined.is_volume:
        raise ValueError('Combined STL failed closed-solid validation.')
    return combined,individual,reports,placements


def main():
    cli = parser()
    a = cli.parse_args()
    try:
        if a.out.exists() and any(a.out.iterdir()) and not a.force:
            raise ValueError('Output directory is not empty; choose another --out or use --force.')
        combined,individual,reports,placements = build_batch(a)
        a.out.mkdir(parents=True, exist_ok=True)
        combined.export(a.out/'molds.stl')
        for key,base,wall,casting in individual:
            folder=a.out/key
            folder.mkdir(exist_ok=True)
            base.export(folder/'base.stl')
            wall.export(folder/'wall.stl')
            casting.export(folder/'casting-preview.stl')
        report = {k: str(v) if isinstance(v, Path) else v for k,v in vars(a).items()}
        report.update(units='mm',shapes=reports,placements=placements,
                      layout_size_mm=combined.extents.tolist(),
                      minimum_floor_mm=a.base_thickness-a.seat_depth-a.vertical_clearance,
                      note='molds.stl contains separate print-oriented bases and walls; not a liquid seal.')
        (a.out/'dimensions.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(f'Created {a.out.resolve() / "molds.stl"}: {len(reports)} molds, {len(placements)} print parts')
        print(f'Layout: {combined.extents.round(2)} mm. Check BOTH dimensions against your printer bed.')
        print('Import STL as millimeters. Test fit first; seal/clamp the joint for liquid casting.')
    except (ValueError, OSError, ET.ParseError) as e:
        cli.exit(2, f'Error: {e}\n')


if __name__ == '__main__':
    main()
