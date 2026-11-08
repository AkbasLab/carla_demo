"""Prevent accidental cross-batch inference contention without changing mission rules."""
from pathlib import Path
import tempfile
import unittest
from agentic_uav.experiments.batch_isolation import batch_isolation


class IsolationTests(unittest.TestCase):
    def test_overlapping_pinned_batch_is_rejected_and_exception_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lock'
            with self.assertRaisesRegex(ValueError,'abort'):
                with batch_isolation('pinned','focused',lock_path=path) as info:
                    self.assertEqual(info['mode'],'exclusive_same_user_vm')
                    with self.assertRaisesRegex(RuntimeError,'Another Phase 17 pinned batch'):
                        with batch_isolation('pinned','severe',lock_path=path):pass
                    raise ValueError('abort')
            with batch_isolation('pinned','focused',lock_path=path):pass

    def test_explicit_override_is_recorded_and_replay_does_not_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lock'
            with batch_isolation('pinned','focused',lock_path=path):
                with batch_isolation('pinned','focused',allow_concurrent=True,lock_path=path) as info:
                    self.assertTrue(info['override']);self.assertEqual(info['mode'],'concurrent_override')
                with batch_isolation('replay','focused',lock_path=path) as info:
                    self.assertEqual(info['mode'],'not_required')


if __name__=='__main__':unittest.main()
