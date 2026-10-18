# SVG casting molds

Generate a two-part casting mold for **every closed shape in an Inkscape SVG**, and arrange all bases and removable walls into **one `molds.stl`**. No Blender required.

## Run with uv

```powershell
git clone https://github.com/lambdawalker/3d.modeling.mold.git
cd 3d.modeling.mold
uv sync --locked
uv run python svg_mold.py examples/shapes.svg
```

The attached example contains four paths and a circle. It generates five molds / ten print parts. With defaults its combined layout is approximately **218.85 × 210.12 × 7.5 mm**. Check your printer's usable area, including any brim.

Dependencies are managed by `pyproject.toml` and `uv.lock`. The script also retains inline dependency metadata so `uv run svg_mold.py ...` works independently, but the project command above uses the lockfile.

```powershell
uv run python svg_mold.py "my-shapes.svg" --depth 8 --layout-width 250 --gap 6 --out my-molds
```

By default, the script preserves physical dimensions from the SVG at 96 DPI, including page/viewBox and group transforms. A unitless SVG is interpreted in CSS pixels (1 px = 25.4/96 mm). Stroke thickness is ignored: each perimeter defines the cavity boundary. `--width 100` overrides **each shape's** width to 100 mm; omit it to retain the relative sizes in your drawing.

To generate only one shape:

```powershell
uv run python svg_mold.py examples/shapes.svg --path-id path4 --width 30 --out circle-mold
```

## Output

- `molds.stl`: all bases and walls, separated in XY and placed on Z=0. Walls are inverted so the broad rim prints first and the tongue prints last. Flip walls over when assembling.
- `01/base.stl`, `01/wall.stl`, `01/casting-preview.stl`: individual files per shape; numbered folders correspond to `dimensions.json`.
- `dimensions.json`: source SVG IDs, casting dimensions and volumes, joint parameters, and bounding-box placements.
- `example-output/`: generated results from the supplied `examples/shapes.svg`, included in this repository.

The combined STL contains **disconnected solids**, not one fused mold plate. Import STL in **millimeters**. A slicer can split the disconnected parts if needed. Casting previews are not included in the print layout.

Layout uses rows with the specified gap. `--layout-width` limits width only; height grows as needed and is printed to the console. Parts are never scaled to fit the bed. A part too wide even after a 90-degree rotation produces an error. Use separate `--path-id` runs if the entire set exceeds your bed.

## Mold construction

The casting floor is the flat top of the base. Walls extend outward from each perimeter. A narrow tongue under each wall fits a matching recessed groove outside the cavity. Wall shoulders rest on the base; vertical clearance prevents the tongue from bottoming out. The groove retains a solid floor underneath.

| Option | Default (mm) | Meaning |
|---|---:|---|
| `--depth` | 6 | Casting depth above base |
| `--wall` | 3 | Wall thickness outward from perimeter |
| `--base-thickness` | 5 | Total base height |
| `--margin` | 6 | Base border outside walls |
| `--tongue` | 1.4 | Registration tongue width |
| `--seat-depth` | 1.5 | Tongue engagement |
| `--clearance` | 0.2 | Horizontal gap on each side of tongue |
| `--vertical-clearance` | 0.2 | Gap under tongue |
| `--curve-step` | 0.25 | Curve sampling length target |
| `--layout-width` | 220 | Maximum layout width |
| `--gap` | 5 | Minimum XY spacing between print parts |

Defaults leave 3.3 mm of material under the groove. Invalid joint dimensions are rejected. Curves are sampled; curve-step controls density, not a guaranteed geometric error bound.

## SVG preparation and limits

Paths, circles, ellipses, rectangles and polygons are converted to perimeters. Each element must contain one closed, simple contour; compound paths with holes/multiple subpaths and self-intersections are rejected with the shape ID. Split unrelated compound paths in Inkscape first. Convert text and live effects to ordinary paths. Remove raster artwork, clips and masks; unlink clones. The SVG should contain only the intended manufacturing outlines, with no decorative/background shapes. This is a geometric importer, not a full SVG renderer (CSS effects and hidden-layer conventions are not a manufacturing selection mechanism). Use `--path-id` when needed.

The registration fit is not a snap lock or a liquid seal. Test print and adjust clearances for your printer. Clamp/seal the joint for liquid casting. There is no draft, shrinkage compensation, gasket or split-wall release; complex shapes may grip the casting. Printed solids can leak even when the STL is watertight. Match print/casting materials and temperatures to your process.

Existing nonempty output directories are protected. `--force` overwrites generated filenames but does not remove unrelated or stale numbered folders; use a fresh output directory when changing the shape count.

## Tests

```powershell
uv run python -m unittest -v
```

Tests cover transforms, dimensions, curved/concave contours, closed positive-volume solids, joint/cavity interference, rejected invalid input, the supplied five-shape SVG, ten separated print solids, bed-width rejection and shape filtering. GitHub Actions runs on Windows and Linux. Local validation was performed on Linux; physical fit has not been tested.

Geometry uses [svgelements](https://github.com/meerk40t/svgelements), [Shapely](https://shapely.readthedocs.io/), [Manifold3D](https://github.com/elalish/manifold) and [Trimesh](https://trimesh.org/).
