"""Evidence reconciliation must not select outcomes or erase provenance."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('repair_phase17', Path(__file__).resolve().parents[1]/'scripts/repair_phase17_calibration.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class RepairTests(unittest.TestCase):
    def test_earliest_finished_attempt_wins_even_when_mission_failed(self):
        first = dict(path='a', started_at_utc='2026-11-07T10:00:00+00:00', finished=True, issues=[], mission_complete=False)
        later = dict(path='b', started_at_utc='2026-11-07T11:00:00+00:00', finished=True, issues=[], mission_complete=True)
        self.assertIs(repair.select_attempt([later, first]), first)

    def test_technical_failure_and_incompatible_attempt_are_not_selected(self):
        bad = dict(path='a', started_at_utc='2026-11-07T10:00:00+00:00', finished=False, issues=[])
        mismatch = dict(path='b', started_at_utc='2026-11-07T11:00:00+00:00', finished=True, issues=['runtime_source_mismatch'])
        self.assertIsNone(repair.select_attempt([bad, mismatch]))

    def test_config_and_runtime_hash_must_match(self):
        entry={'experiment_id':'case','settings':{'dt':0.2}}
        manifest={'requested_configuration':entry,'provenance':{'source_sha256':{'a':'1'}}}
        self.assertEqual(repair.compatible(manifest, entry, {'a':'1'}), [])
        self.assertIn('runtime_source_mismatch', repair.compatible(manifest, entry, {'a':'2'}))
        self.assertIn('requested_configuration_mismatch', repair.compatible(manifest, {'settings':{}}, {'a':'1'}))

    @patch.object(repair, 'sha', return_value='hash')
    @patch.object(repair, 'evaluator_hash', return_value='evaluator')
    def test_per_attempt_registration_precedes_execution(self, *_):
        registration=dict(evaluator_source_sha256='evaluator',contract_sha256='hash',definitions_sha256='hash',registered_at_utc='2026-11-07T10:00:00+00:00')
        self.assertTrue(repair.registration_valid({'started_at_utc':'2026-11-07T10:01:00+00:00'}, registration))
        self.assertFalse(repair.registration_valid({'started_at_utc':'2026-11-07T09:59:00+00:00'}, registration))

    @patch.object(repair, 'sha', return_value='hash')
    @patch.object(repair, 'evaluator_hash', return_value='current')
    def test_changed_metric_contract_is_not_prespecified(self, *_):
        registration=dict(evaluator_source_sha256='old',contract_sha256='hash',definitions_sha256='hash',registered_at_utc='2026-11-07T10:00:00+00:00')
        self.assertFalse(repair.registration_valid({'started_at_utc':'2026-11-07T10:01:00+00:00'}, registration))


if __name__=='__main__':
    unittest.main()
