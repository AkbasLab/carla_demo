import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from agentic_uav.coordination.mission_view import scale_routes,overview_geometry,draw_overview,save_route_map


class ViewTests(unittest.TestCase):
    def test_scale_preserves_altitude_offsets_and_original(self):
        source=dict(vehicles={'D':dict(frame_offset_m=[0,5,0])},tasks=[dict(waypoints=[[2,5,25],[6,6,25]])])
        result=scale_routes(source,3)
        self.assertEqual(result['tasks'][0]['waypoints'],[[6,15,25],[18,18,25]])
        self.assertEqual(result['vehicles'],source['vehicles'])
        self.assertEqual(source['tasks'][0]['waypoints'][0],[2,5,25])
        with self.assertRaises(ValueError):scale_routes(source,0)

    def test_camera_frames_route_and_starting_points(self):
        x,y,z=overview_geometry([[0,0,25],[18,48,25]],[0,0,28],40)
        self.assertEqual((x,y),(9,24))
        self.assertGreater(z,60)

    def test_spectator_and_debug_labels(self):
        transforms=[];labels=[]
        class Location:
            def __init__(self,*args,**kw):self.args=args;self.kw=kw
        api=N(Location=Location,Rotation=lambda **kw:kw,Transform=lambda *args:args,Color=lambda *args:args)
        debug=N(draw_point=lambda *a,**kw:None,draw_line=lambda *a,**kw:None,
                draw_string=lambda where,label,**kw:labels.append(label))
        world=N(get_spectator=lambda:N(set_transform=lambda t:transforms.append(t)),debug=debug)
        draw_overview(world,api,{'A':[[2,0,25],[6,0,25]]},{'Drone1':[0,0,25]},[0,0,28],40,60)
        self.assertEqual(len(transforms),1)
        self.assertTrue(any('WP1' in text for text in labels))
        self.assertTrue(any('Drone1' in text for text in labels))

    def test_route_map_render(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'routes.png'
            save_route_map({'A':[[2,0,25],[6,0,25]]},{'Drone1':[0,0,25]},out)
            self.assertGreater(out.stat().st_size,100)
