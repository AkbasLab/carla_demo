import json
import tempfile
import unittest
from pathlib import Path
from scripts.plot_phase7_protocol import generate_plots, protocol_metrics
from agentic_uav.comm.phase7_demo import run_protocol_demo


class Phase7Plots(unittest.TestCase):
    def test_unique_send_is_not_recipient_count(self):
        rows=[dict(message_id='one',sender_id='a',recipient_id=r,message_type='HEARTBEAT',
                   sent_time=0.,creation_time=0.,actual_delivery_time=.1,status='delivered',
                   size_bytes=100,influenced_decision=False) for r in ['b','c','d']]
        m=protocol_metrics(rows)
        self.assertEqual(m['unique_messages_sent'],1)
        self.assertEqual(m['recipient_deliveries'],3)
        self.assertEqual(m['serialized_unique_bytes'],100)
        self.assertEqual(m['serialized_recipient_bytes'],300)
        self.assertAlmostEqual(m['send_to_receive_s']['mean'],.1)
        self.assertIsNone(protocol_metrics([])['delivery_ratio'])

    def test_render_saved_mock_and_live_schema(self):
        for live in (False,True):
            with self.subTest(live=live),tempfile.TemporaryDirectory() as d:
                run_protocol_demo(3,output_dir=d)
                path=Path(d)
                if live:
                    beliefs=json.loads((path/'beliefs.json').read_text())
                    for b in beliefs:
                        b['height_above_start_m']=3.
                        b['speed_mps']=.5
                    (path/'beliefs.json').write_text(json.dumps(beliefs))
                self.assertTrue(generate_plots(path).exists())
                self.assertGreater((path/'phase7_metrics.pdf').stat().st_size,100)
                m=json.loads((path/'protocol_metrics.json').read_text())
                self.assertEqual(m['delivery_ratio'],1)
                self.assertEqual(m['recipient_deliveries'],111)
                import matplotlib.pyplot as plt
                self.assertEqual(plt.get_fignums(),[])
