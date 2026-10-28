import csv
import json
import tempfile
import unittest
from pathlib import Path
from scripts.plot_experiment_d_resilience import generate_plots, recovery_distances


class PlotTests(unittest.TestCase):
    def test_path_length_differs_from_displacement(self):
        rows=[dict(wall_elapsed_s=i,x=x,y=0,z=25) for i,x in enumerate([0,2,0])]
        result=recovery_distances(rows,dict(failsafe_detection_s=0,recovery_observed_s=2))
        self.assertEqual(result['recovery_path_length_m'],4)
        self.assertEqual(result['recovery_net_displacement_m'],0)
        self.assertIsNone(recovery_distances(rows,{})['recovery_path_length_m'])

    def test_render_with_and_without_recovery(self):
        import matplotlib.pyplot as plt
        for recovered in (True,False):
            with self.subTest(recovered=recovered),tempfile.TemporaryDirectory() as d:
                p=Path(d)
                rows=[dict(wall_elapsed_s=i*.1,x=i*.1,y=0,z=25,speed_mps=max(0,1-i*.1),heartbeat_age_s=i*.1,
                    heartbeat_delivered=int(i<5),height_above_configured_ground_m=3) for i in range(20)]
                with (p/'telemetry.csv').open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
                summary=dict(status='completed',parameters=dict(recovery='hover',inject_at=.5,safe_speed=.25,timeout=.5,cruise_height=3),
                    first_undelivered_heartbeat_s=.5,failsafe_detection_s=1 if recovered else None,
                    recovery_observed_s=1.8 if recovered else None,collision_seen=False)
                (p/'summary.json').write_text(json.dumps(summary))
                if recovered:
                    (p/'commands.json').write_text(json.dumps([dict(sequence=1,at_s=.1,received_at_s=.2,
                        inference_latency_s=.1,target=[1,0,25],decision='accepted')]))
                self.assertTrue(generate_plots(p).exists())
                self.assertGreater((p/'resilience_metrics.pdf').stat().st_size,100)
                metrics=json.loads((p/'plot_metrics.json').read_text())
                self.assertEqual(metrics['recovery_path_length_m'] is None,not recovered)
                self.assertEqual(plt.get_fignums(),[])

    def test_missing_telemetry_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'summary.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'No telemetry'):
                generate_plots(p)
