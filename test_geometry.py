import tempfile
import unittest
from pathlib import Path
import trimesh
from svg_mold import outline, parser, generate

class GeometryTests(unittest.TestCase):
    def make(self, data, extra=()):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'shape.svg'
            f.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><g transform="translate(3,7) scale(2)"><path id="test" d="'+data+'"/></g></svg>')
            a=parser().parse_args([str(f),'--width','80',*extra])
            p=outline(f,None,a.width,a.curve_step)
            return p,a

    def test_fit_and_dimensions(self):
        for path in ['M0 0H40V30H0Z','M0 0H40V10H20V30H0Z','M0 0 C50 -20 60 40 30 40 L0 30Z']:
            with self.subTest(path=path):
                p,a=self.make(path)
                base,wall,cast=generate(p,a)
                self.assertAlmostEqual(p.bounds[2]-p.bounds[0],80)
                for mesh in (base,wall,cast):
                    self.assertTrue(mesh.is_watertight and mesh.is_volume)
                    self.assertEqual(mesh.body_count,1)
                collision=trimesh.boolean.intersection([base,wall],engine='manifold')
                self.assertLess(abs(collision.volume),1e-6)
                collision=trimesh.boolean.intersection([cast,wall],engine='manifold')
                self.assertLess(abs(collision.volume),1e-6)
                self.assertAlmostEqual(base.bounds[0,2],0)
                self.assertAlmostEqual(base.bounds[1,2],a.base_thickness)
                self.assertAlmostEqual(cast.volume,p.area*a.depth,places=2)
    def test_open_rejected(self):
        with self.assertRaisesRegex(ValueError,'open'):
            self.make('M0 0H40V30H0')
    def test_crossing_rejected(self):
        with self.assertRaises(ValueError):
            self.make('M0 0L40 30L0 30L40 0Z')
    def test_floor_and_clearance(self):
        for extra in [('--base-thickness','1'),('--clearance','1')]:
            p,a=self.make('M0 0H40V30H0Z',extra)
            with self.assertRaises(ValueError):
                generate(p,a)


class BatchTests(unittest.TestCase):
    def test_uploaded_svg(self):
        from svg_mold import build_batch
        a=parser().parse_args(['examples/shapes.svg'])
        combined,individual,reports,placements=build_batch(a)
        self.assertEqual(len(individual),5)
        self.assertEqual(len(placements),10)
        self.assertEqual(combined.body_count,10)
        self.assertTrue(combined.is_watertight and combined.is_volume)
        circle=next(r for r in reports if r['svg_id']=='path4')
        self.assertAlmostEqual(circle['casting_size_mm'][0],21.683628,places=3)
        self.assertLessEqual(combined.extents[0],a.layout_width+1e-6)
        for i,p in enumerate(placements):
            lo,hi=p['bounds_mm']
            self.assertAlmostEqual(lo[2],0,places=6)
            for q in placements[i+1:]:
                qlo,qhi=q['bounds_mm']
                self.assertTrue(hi[0]+a.gap <= qlo[0]+1e-6 or qhi[0]+a.gap <= lo[0]+1e-6 or
                                hi[1]+a.gap <= qlo[1]+1e-6 or qhi[1]+a.gap <= lo[1]+1e-6)
    def test_filter_and_width(self):
        from svg_mold import build_batch
        a=parser().parse_args(['examples/shapes.svg','--path-id','path4','--width','30'])
        m,items,reports,_=build_batch(a)
        self.assertEqual(len(items),1)
        self.assertAlmostEqual(reports[0]['casting_size_mm'][0],30,places=4)
    def test_too_small_layout(self):
        from svg_mold import build_batch
        a=parser().parse_args(['examples/shapes.svg','--layout-width','10'])
        with self.assertRaisesRegex(ValueError,'cannot fit'):
            build_batch(a)

if __name__=='__main__': unittest.main()
