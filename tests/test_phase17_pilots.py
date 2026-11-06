import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agentic_uav.experiments import pilots
from agentic_uav.experiments.runner import run_batch
from agentic_uav.policy.mission import load_mission


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config=pilots.read('configs/phase17/pilot.example.json')
        self.input=self.root/'input.json';self.write_input()

    def write_input(self):
        self.input.write_text(json.dumps(self.config))

    def test_small_matrix_and_seed_separation_preserve_workload(self):
        plan=pilots.prepare(self.input,self.root/'plan')
        self.assertEqual(plan['planned_experiments'],48)
        batch=pilots.read(self.root/'plan/pilot_batch.json')['experiments']
        self.assertEqual(len({e['experiment_id'] for e in batch}),48)
        self.assertEqual({e['team_size'] for e in batch},{2,4})
        self.assertEqual({e['architecture'] for e in batch},{'C','D'})
        self.assertEqual({e['random_seed'] for e in batch},{41,42,43})
        missions=[pilots.read(pilots.resolve(p)) for p in plan['mission_files'].values()]
        self.assertEqual(missions[0]['tasks'],missions[1]['tasks'])
        self.assertEqual(len(missions[0]['tasks']),4)
        for e in batch:
            self.assertEqual(sum(map(len,e['settings']['initial_assignments'].values())),4)
            self.assertEqual(e['settings']['clock_mode'],'simulated')
            if e['architecture']=='D':self.assertEqual(e['planner'],'replay')
        with self.assertRaises(ValueError):load_mission(pilots.resolve(plan['mission_files'][2]))
        m,_,_,_=load_mission(pilots.resolve(plan['mission_files'][2]),allowed_team_sizes=(2,4))
        self.assertEqual(len(m['vehicles']),2)

    def test_generated_routes_fit_existing_static_deadline_without_relaxing_guardian(self):
        from agentic_uav.control.runtime_guardian import Config,RuntimeGuardian,State,Action
        plan=pilots.prepare(self.input,self.root/'feasibility')
        for path in plan['mission_files'].values():
            m=pilots.read(pilots.resolve(path));g=RuntimeGuardian(Config(**m['guardian']))
            aid,v=next(iter(m['vehicles'].items()));route=m['tasks'][0]['waypoints']
            action=Action('check',aid,'MOVE',0,30,tuple(tuple(p) for p in route),1)
            result=g.evaluate(action,State(aid,tuple(v['start_position']),0,80,tuple(v['home'])),0)
            self.assertEqual(result.outcome.value,'APPROVE')
            self.assertEqual(g.config.max_action_duration_s,30)

    def test_bad_seeds_network_and_shared_settings_are_rejected(self):
        mutations=[dict(held_out_seeds=[42]),dict(pilot_seeds=[41,41]),dict(settings={'dt':0}),
                   dict(settings={'policy':{}}),dict(fail_at_s=600),dict(architectures=['A','D'])]
        for change in mutations:
            with self.subTest(change=change),self.assertRaises(ValueError):pilots.validate_config({**self.config,**change})
        c=copy.deepcopy(self.config);c['network_profiles']['nominal']['packet_loss_probability']=.1
        with self.assertRaises(ValueError):pilots.validate_config(c)

    def test_prepared_files_are_immutable_and_outputs_not_overwritten(self):
        pilots.prepare(self.input,self.root/'plan')
        with self.assertRaises(ValueError):pilots.prepare(self.input,self.root/'plan')
        p=self.root/'plan/fixtures/team_2.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(ValueError):pilots.verify_plan(self.root/'plan')

    def test_pinned_preflight_failure_preserves_plan_before_any_mission(self):
        with patch.object(pilots.OllamaProvider,'verify',side_effect=RuntimeError('server unavailable')),patch.object(pilots,'run_batch') as run:
            with self.assertRaises(RuntimeError):pilots.run_pilots(self.input,self.root/'pinned','pinned')
        run.assert_not_called();self.assertTrue((self.root/'pinned/pilot_error.json').exists())
        self.assertFalse((self.root/'pinned/runs').exists())

    def test_two_drone_real_runner_and_nine_panel_plot(self):
        # Actual transport/policies/kinematics/guardian, not a synthetic success summary.
        m=pilots.read('configs/phase12/mission.example.json');m['vehicles']=dict(list(m['vehicles'].items())[:2])
        mission=self.root/'mission.json';mission.write_text(json.dumps(m))
        entry=dict(experiment_id='two_drone_control',architecture='D',scenario='test',team_size=2,network_profile='nominal',
                   failure_profile='none',random_seed=41,planner='replay',settings=dict(mission_config=str(mission),
                   initial_assignments={'Drone1':['SEARCH_SECTOR_A','SEARCH_SECTOR_C'],'Drone2':['SEARCH_SECTOR_B','SEARCH_SECTOR_D']},
                   ticks=500,dt=.1,bid_window=.5,lease_seconds=10,decision_interval=.2,resilience={'enabled':True}))
        batch=self.root/'batch.json';batch.write_text(json.dumps(dict(schema_version=1,experiments=[entry])))
        control=copy.deepcopy(entry);control.update(experiment_id='two_drone_C',architecture='C',planner='deterministic')
        batch.write_text(json.dumps(dict(schema_version=1,experiments=[entry,control])))
        result=run_batch(batch,self.root/'run',evaluate=True)
        self.assertEqual(result['successful_missions'],2)
        folder=self.root/'run/two_drone_control'
        evidence=pilots._run_evidence(folder)
        self.assertEqual(evidence['log_issues'],[]);self.assertFalse(evidence['llm_inference'])
        from agentic_uav.experiments.pilot_plots import plot_run
        target=self.root/'timeline.png';plot_run(folder,target)
        self.assertGreater(target.stat().st_size,10000)
        self.assertEqual(result['evaluation']['evidence_issues'],0)
        self.assertTrue(result['evaluation']['prespecified'])

    def test_incomplete_batch_remains_visible_and_cannot_freeze(self):
        pilots.prepare(self.input,self.root/'plan')
        report=pilots.analyze(self.root/'plan',plots=False)
        self.assertEqual(len(report['runs']),48)
        self.assertFalse(report['eligible_for_freeze'])
        self.assertIn('incomplete_or_inconsistent_run_evidence',report['freeze_blockers'])
        self.assertIn('validation_replay_cannot_select_final_agentic_configuration',report['freeze_blockers'])
        with self.assertRaises(ValueError):pilots.freeze(self.root/'plan',self.root/'frozen',self.root/'unused.json')

    def synthetic_calibration(self):
        # Test-only records isolate calibration math; never written as pilot flight evidence.
        root=self.root/'synthetic';pilots.prepare(self.input,root,'pinned')
        batch=pilots.read(root/'pilot_batch.json');entries={e['experiment_id']:e for e in batch['experiments']}
        (root/'runs/metrics').mkdir(parents=True)
        rows=[]
        for e in entries.values():
            rows.append(dict(experiment_id=e['experiment_id'],evidence_issues=[],primary=dict(
                mission=dict(components=dict(route_work_fraction=1)),completion_time=dict(value_s=100))))
        pilots.write_json(root/'runs/metrics/metrics.json',rows)
        pilots.write_json(root/'runs/metrics/evaluation_summary.json',dict(prespecified=True,evidence_issues=0))
        def fake(folder):
            e=entries[folder.name];actual=e['architecture']=='D'
            return dict(log_issues=[],event_counts={'LLM_CALLED':1 if actual else 0},runtime_error=None,
                mission_complete=e['network_profile']=='nominal' or e['random_seed']!=42,
                source_hashes={'agentic_uav/policy/structured.py':pilots.digest('agentic_uav/policy/structured.py')},
                fault_observed=e['failure_profile']!='none',fault_owned_tasks=['SEARCH_SECTOR_A'],fault_during_motion=True,
                llm_inference=actual,productive_llm_decisions=1 if actual else 0,
                delivered_fraction_resolved=1 if e['network_profile']=='nominal' else .6,
                model=dict(provider='ollama',model='phase12-agent:pinned',digest=self.config['model']['model_digest'],options=dict(seed=e['random_seed'],temperature=0)))
        return root,fake

    def test_calibration_compares_multiple_seeds_without_conflating_seed_options(self):
        root,fake=self.synthetic_calibration()
        with patch.object(pilots,'_run_evidence',side_effect=fake):report=pilots.analyze(root,plots=False)
        self.assertTrue(report['eligible_for_freeze'],report['freeze_blockers'])
        self.assertAlmostEqual(report['calibration']['severe_control_success_rate'],2/3)
        def trivial(folder):return {**fake(folder),'mission_complete':True}
        with patch.object(pilots,'_run_evidence',side_effect=trivial):report=pilots.analyze(root,plots=False)
        self.assertIn('severe_control_outcomes_degenerate_all_fail_or_all_succeed',report['freeze_blockers'])
        def idle_fault(folder):return {**fake(folder),'fault_during_motion':False}
        with patch.object(pilots,'_run_evidence',side_effect=idle_fault):report=pilots.analyze(root,plots=False)
        self.assertIn('fault_did_not_interrupt_owned_moving_work',report['freeze_blockers'])

    def test_freeze_locks_rules_metrics_scenario_and_unseen_seed_batch(self):
        root,fake=self.synthetic_calibration()
        rationale={k:'Test-only written rationale explaining this explicit calibration selection in sufficient detail.' for k in ['nominal','severe','scenario_families','selection_reason']}
        why=self.root/'why.json';pilots.write_json(why,rationale)
        out=self.root/'lock'
        with patch.object(pilots,'_run_evidence',side_effect=fake):lock=pilots.freeze(root,out,why)
        pilots.verify_frozen(out)
        final=pilots.read(out/'final_batch.json')['experiments']
        self.assertEqual(len(final),160)
        self.assertFalse({e['random_seed'] for e in final}&set(lock['pilot_seeds']))
        self.assertEqual({e['random_seed'] for e in final},set(lock['held_out_seeds']))
        p=out/'final_batch.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(ValueError):pilots.verify_frozen(out)

    def test_silence_does_not_count_as_inflight_fault_without_active_move(self):
        # Real short fault run: empty/idle ownership is diagnosed, never relabelled.
        root=self.root/'prepared';plan=pilots.prepare(self.input,root)
        entry=pilots.read(root/'pilot_batch.json')['experiments'][1]
        entry['settings'].update(ticks=20,dt=.1)
        entry['settings']['scenario']['fail_at_s']=.1
        batch=self.root/'fault.json';pilots.write_json(batch,dict(schema_version=1,experiments=[entry]))
        run_batch(batch,self.root/'fault_runs')
        e=pilots._run_evidence(self.root/'fault_runs'/entry['experiment_id'])
        self.assertTrue(e['fault_observed']);self.assertFalse(e['fault_during_motion'])


if __name__=='__main__':unittest.main()
