import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch

from agentic_uav.control.oba_recovery import RecoveryGuardian, segment_hits_box

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'configs/experiments/d_resilience.example.json').read_text())


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(CONFIG)
        self.config['landing_site']['surveyed_clear'] = True
        self.g = RecoveryGuardian.from_config(self.config)

    def test_exact_intersection_not_midpoint(self):
        box = dict(x_min=2, x_max=3, y_min=-1, y_max=1, z_min=20, z_max=28)
        self.assertTrue(segment_hits_box((0, 0, 25), (10, 0, 25), box))
        self.assertFalse(segment_hits_box((0, 2, 25), (10, 2, 25), box))

    def test_route_and_corridor(self):
        self.assertTrue(self.g.check_segment((10, 0, 25), (0, 0, 25))[0])
        self.assertTrue(self.g.approve_landing((0, 0, 25), .3)[0])
        self.g.keepouts = [dict(x_min=.5, x_max=.7, y_min=-.1, y_max=.1, z_min=26, z_max=27)]
        self.assertFalse(self.g.approve_landing((0, 0, 25), .3)[0])

    def test_fail_closed(self):
        self.g.site['surveyed_clear'] = False
        self.assertFalse(self.g.approve_landing((0, 0, 25), .3)[0])
        self.assertFalse(self.g.check_segment((100, 0, 25), (0, 0, 25))[0])
        self.assertTrue(self.g.violations((float('nan'), 0, 25)))

    def test_nonzero_ground_origin(self):
        self.assertEqual(self.g.violations((0, 0, 25)), [])
        self.assertTrue(self.g.violations((0, 0, -25)))


class BoundExpansionTests(unittest.TestCase):
    def test_expansion_preserves_other_configuration_and_source(self):
        spec = importlib.util.spec_from_file_location('experiment_d_bounds', ROOT / 'scripts/run_experiment_d_resilience.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'bounds.json'
            cfg = copy.deepcopy(CONFIG)
            cfg['flight_bounds']['x_min'] = -200
            path.write_text(json.dumps(cfg))
            self.assertEqual(m.load_boundary_config(path), cfg)
            expanded = m.load_boundary_config(path, True)
            self.assertEqual(expanded['flight_bounds']['x_min'], -200)
            self.assertEqual(expanded['flight_bounds']['z_min'], -100)
            self.assertEqual(expanded['flight_bounds']['z_max'], 100)
            self.assertEqual(expanded['keepouts'], cfg['keepouts'])
            self.assertEqual(expanded['landing_site'], cfg['landing_site'])
            self.assertEqual(json.loads(path.read_text()), cfg)
            guardian = RecoveryGuardian.from_config(expanded)
            self.assertTrue(guardian.inside((50, 50, 0)))
            self.assertFalse(guardian.inside((101, 0, 0)))


class IntegrationTests(unittest.TestCase):
    def exercise(self, mode, loss, collision=False, llm=False):
        spec = importlib.util.spec_from_file_location('experiment_d', ROOT / 'scripts/run_experiment_d_resilience.py')
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        class Clock:
            t = 0.
            def monotonic(self): return self.t
            def sleep(self, d): self.t += max(d, .001)
        clock = Clock()
        class Future:
            def join(self): pass
        def vector(t): return N(x_val=t[0], y_val=t[1], z_val=t[2])
        class Air:
            pos = (0, 0, 28)
            landed = 0
            lands = 0
            def confirmConnection(self): pass
            def enableApiControl(self, enabled): pass
            def armDisarm(self, armed): pass
            def takeoffAsync(self, **kw): self.pos=(0,0,25);self.landed=1;return Future()
            def moveToPositionAsync(self, x, y, z, **kw): self.pos=(x,y,z);return Future()
            def hoverAsync(self): return Future()
            def landAsync(self, **kw): self.lands+=1;self.pos=(0,0,28);self.landed=0;return Future()
            def getMultirotorState(self):
                return N(kinematics_estimated=N(position=vector(self.pos),linear_velocity=vector((0,0,0))),landed_state=self.landed,timestamp=int(clock.t*1e9))
            def simGetCollisionInfo(self):
                hit = collision and clock.t > 2
                return N(has_collided=hit, time_stamp=1 if hit else 0)
        class Worker:
            def __init__(self, *a): self.pending=None
            def submit(self, sequence, state):
                self.pending=(sequence,clock.t,clock.t+(.1 if sequence==1 else 3))
            def poll(self):
                if self.pending is None or clock.t<self.pending[2]: return None
                sequence,created,_=self.pending;self.pending=None
                return dict(sequence=sequence,target=(10,0,25),created_at=created,
                            expires_at=created+20,inference_latency_s=clock.t-created)
            def close(self): pass
        air = Air()
        settings=N(synchronous_mode=True)
        world=N(get_settings=lambda:copy.copy(settings),apply_settings=lambda x:None,
                get_snapshot=lambda:N(timestamp=N(elapsed_seconds=clock.t)))
        carla=N(Client=lambda *a:N(set_timeout=lambda x:None,get_world=lambda:world))
        airsim=N(MultirotorClient=lambda **kw:air,LandedState=N(Landed=0))
        with tempfile.TemporaryDirectory() as d:
            config=copy.deepcopy(CONFIG);config['landing_site']['surveyed_clear']=True
            cfg=Path(d)/'config.json';cfg.write_text(json.dumps(config))
            argv=['run','--boundary-config',str(cfg),'--output-dir',d,'--recovery',mode,
                  '--loss',str(loss),'--duration','10','--inject-at','1','--timeout','1',
                  '--stable-seconds','.3','--log-every','1000']
            if llm:
                argv += ['--command-source','llm','--communication-only','--llm-interval','0.5']
            with patch.object(m,'LLMCommandWorker',Worker),patch('sys.argv',argv),patch.object(m,'time',clock),patch.dict('sys.modules',{'airsim':airsim,'carla':carla}):
                m.run(m.parse_args())
            return json.loads((Path(d)/'summary.json').read_text()),air.lands

    def test_oba_lands_after_timeout_and_observation(self):
        s,lands=self.exercise('oba-land',1)
        self.assertTrue(s['recovery_success'])
        self.assertEqual(lands,1)
        self.assertGreater(s['recovery_time_from_detection_s'],0)
        self.assertEqual(s['boundary_violation_samples'],0)
        self.assertGreater(s['events'][-1]['elapsed_s'],s['failsafe_detection_s'])

    def test_no_loss_no_recovery_or_cleanup_landing(self):
        s,lands=self.exercise('oba-land',0)
        self.assertIsNone(s['failsafe_detection_s'])
        self.assertFalse(s['recovery_success'])
        self.assertEqual(lands,0)

    def test_disabled_recovery_detects_but_never_lands(self):
        s,lands=self.exercise('none',1)
        self.assertIsNotNone(s['failsafe_detection_s'])
        self.assertEqual(lands,0)
        self.assertFalse(s['recovery_success'])

    def test_llm_late_command_cannot_cancel_hover(self):
        s,lands=self.exercise('hover',1,llm=True)
        decisions=[c['decision'] for c in s['command_events']]
        self.assertIn('accepted',decisions)
        self.assertIn('suppressed_after_timeout',decisions)
        self.assertTrue(s['sustained_hover_observed'])
        self.assertEqual(lands,0)
        self.assertLess(s['failsafe_detection_s'],3)

    def test_collision_blocks_landing(self):
        s,lands=self.exercise('oba-land',1,collision=True)
        self.assertEqual(lands,0)
        self.assertFalse(s['recovery_success'])
        self.assertTrue(s['collision_seen'])


if __name__ == '__main__':
    unittest.main()
