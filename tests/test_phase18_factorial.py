import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agentic_uav.experiments import factorial as f
from agentic_uav.experiments import pilots
from agentic_uav.experiments.comparison import run_comparison
from agentic_uav.experiments.runner import run_experiment, write_json
from agentic_uav.policy.mission import load_mission


class FactorialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.c=f.read('configs/phase18/factorial.example.json')
        self.pilot=f.read('configs/phase18/calibration_pilot.example.json')
        base=f.read('configs/phase12/mission.example.json')
        self.missions={4:base,2:dict(base,vehicles=dict(list(base['vehicles'].items())[:2]))}

    def fixture_paths(self,sizes=(2,4)):
        out=self.root/('fixtures'+''.join(map(str,sizes)));out.mkdir()
        return f.materialize(self.missions,sizes,out)

    def entry(self,architecture='A'):
        c=copy.deepcopy(self.c);c.update(architectures=[architecture],team_sizes=[2,4],conditions=['nominal'],failure_profiles=['none'])
        paths=self.fixture_paths()
        entry=next(e for e in f.entries(c,self.pilot,paths,[101],'held_out')['experiments'] if e['team_size']==4)
        entry['settings'].update(clock_mode='simulated',ticks=500,dt=.1,bid_window=.5,lease_seconds=10,decision_interval=.2)
        if architecture in 'BD':entry['settings']['policy']=dict(provider='replay',model=None,model_digest=None,ollama_url='http://localhost:11434');entry['planner']='replay'
        return entry

    def test_design_counts_and_twenty_reserved_seeds(self):
        source=self.root/'design.json';write_json(source,self.c)
        p=f.plan(source,self.root/'draft')
        self.assertEqual((p['cell_count'],p['planned_runs']),(64,1280))
        c=f.read('configs/phase18/factorial.eight.example.json')
        self.assertEqual(len(f.cells(f.validate_design(c)))*c['replications'],1920)
        self.assertEqual(set(self.c['test_seeds']),set(self.pilot['held_out_seeds']))
        with self.assertRaises(FileExistsError):f.plan(source,self.root/'draft')

    def test_invalid_seed_sets_and_factors_rejected(self):
        for change in [dict(test_seeds=[42]),dict(validation_seeds=[41,42,101]),dict(team_sizes=[8]),
                       dict(max_attempts_per_seed=0),dict(replications=19),dict(architectures=['D','D']),dict(partition_interval_s=[5,5])]:
            with self.subTest(change=change),self.assertRaises(ValueError):f.validate_design({**self.c,**change})

    def test_blocked_main_does_not_contact_model_or_start_mission(self):
        with patch.object(f,'model_preflight') as model,patch.object(f,'run_experiment') as run:
            with self.assertRaises(FileNotFoundError):f.execute(self.root/'no_lock',self.root/'results')
            with self.assertRaises(FileNotFoundError):f.prepare('configs/phase18/factorial.example.json',self.root/'no_pilot',self.root/'no_validation',self.root/'definition')
        model.assert_not_called();run.assert_not_called()

    def test_locked_inputs_reject_inadequate_reserved_pool_and_overlap(self):
        lock=dict(profile='pinned',held_out_seeds=list(range(101,111)),pilot_seeds=[41,42,43])
        folder=self.root/'lock';folder.mkdir();write_json(folder/'pilot_config.json',self.pilot)
        with patch.object(f,'verify_frozen',return_value=lock),self.assertRaisesRegex(ValueError,'reserved'):
            f.locked_inputs(self.c,folder)
        lock['held_out_seeds']=list(range(101,121));c=copy.deepcopy(self.c);c['validation_seeds']=[41,44,45]
        with patch.object(f,'verify_frozen',return_value=lock),self.assertRaisesRegex(ValueError,'overlap'):
            f.locked_inputs(c,folder)

    def test_common_inputs_order_and_partitions_use_actual_team(self):
        paths=self.fixture_paths((2,4,8));c={**self.c,'team_sizes':[2,4,8]}
        batch=f.entries(c,self.pilot,paths,[101],'held_out')['experiments']
        self.assertEqual(batch,f.entries(c,self.pilot,paths,[101],'held_out')['experiments'])
        grouped={}
        for e in batch:
            k=(e['team_size'],e['network_profile'],e['failure_profile'],e['random_seed'])
            grouped.setdefault(k,[]).append(e)
            if e['network_profile']=='partitioned':
                members=[a for group in e['settings']['network']['partitions'][0]['groups'] for a in group]
                self.assertEqual(set(members),set(f.read(paths[str(e['team_size'])])['vehicles'])|{f.CONTROLLER})
        for group in grouped.values():
            self.assertEqual(len(group),4)
            self.assertTrue(all(e['settings']==group[0]['settings'] for e in group))
        eight=next(e for e in batch if e['team_size']==8 and e['architecture']=='B')
        self.assertEqual(sum(bool(v) for v in eight['settings']['initial_assignments'].values()),4)
        m=f.read(paths['8']);self.assertEqual(m['tasks'],self.missions[4]['tasks'])
        with self.assertRaises(ValueError):load_mission(paths['8'])

    def test_eight_drone_mock_accepts_idle_assignments(self):
        paths=self.fixture_paths((8,));m=f.read(paths['8']);ids=list(m['vehicles'])
        assignments={a:[] for a in ids}
        for i,t in enumerate(m['tasks']):assignments[ids[i]].append(t['task_id'])
        s=run_comparison(dict(architecture='B',mission_config=paths['8'],initial_assignments=assignments,
            output_dir=str(self.root/'eight_run'),ticks=500,dt=.1,bid_window=.5,lease_seconds=10,decision_interval=.2))
        self.assertIsNone(s['error']);self.assertTrue(s['mission_complete'])
        self.assertEqual(s['duplicate_task_completions'],0)

    def test_real_completed_and_timed_out_runs_are_both_technically_valid(self):
        entry=self.entry();entry['settings']['ticks']=2000;out=self.root/'runs';out.mkdir()
        sources=f.source_hashes()
        run_experiment(entry,out)
        a=f.assess_attempt(out/entry['experiment_id'],entry,sources)
        self.assertTrue(a['technical_valid'],a['exclusion_reasons'])
        self.assertTrue(a['metrics']['primary']['mission']['success'])
        short=copy.deepcopy(entry);short['experiment_id']='short';short['settings']['ticks']=1
        run_experiment(short,out)
        b=f.assess_attempt(out/'short',short,sources)
        self.assertTrue(b['technical_valid'],b['exclusion_reasons'])
        self.assertFalse(b['metrics']['primary']['mission']['success'])
        self.assertEqual(b['metrics']['primary']['completion_time']['status'],'timeout')
        # Corrupting evidence is technical; an unsuccessful outcome alone is not.
        (out/'short/run/messages.json').write_text('{broken')
        b=f.assess_attempt(out/'short',short,sources)
        self.assertIn('missing_or_corrupt_artifacts',b['exclusion_reasons'])

    def test_configuration_and_model_mismatch_are_technical(self):
        entry=self.entry('B');out=self.root/'runs';out.mkdir();sources=f.source_hashes()
        run_experiment(entry,out)
        # Replay is useful software evidence but cannot impersonate a pinned-model replication.
        a=f.assess_attempt(out/entry['experiment_id'],entry,sources)
        self.assertIn('model_identity_mismatch',a['exclusion_reasons'])
        wrong=copy.deepcopy(entry);wrong['settings']['ticks']+=1
        b=f.assess_attempt(out/entry['experiment_id'],wrong,sources)
        self.assertIn('configuration_or_provenance_mismatch',b['exclusion_reasons'])

    def synthetic_definition(self,entry):
        root=self.root/'definition';root.mkdir()
        c=copy.deepcopy(self.c);c.update(test_seeds=[101],replications=1)
        write_json(root/'design.json',c);write_json(root/'pilot_inputs.json',self.pilot)
        write_json(root/'final_batch.json',dict(schema_version=1,experiments=[entry]))
        write_json(root/'definition_lock.json',dict(source_sha256=f.source_hashes()))
        return root

    def test_first_valid_attempt_is_retained_even_if_incomplete(self):
        entry=self.entry();entry['settings']['ticks']=1;definition=self.synthetic_definition(entry)
        out=self.root/'results';(out/'attempts').mkdir(parents=True)
        first=copy.deepcopy(entry);first['experiment_id']+='_a1';run_experiment(first,out/'attempts')
        with patch.object(f,'verify_definition',return_value=f.read(definition/'definition_lock.json')):
            report=f.summarize(definition,out)
        self.assertTrue(report['exit_criterion_passed']);self.assertEqual(report['successful_missions'],0)
        self.assertEqual(report['attempts'],1)

    def test_resume_retries_interrupted_same_seed_and_never_repeats_valid(self):
        entry=self.entry();entry['settings']['ticks']=1;definition=self.synthetic_definition(entry)
        out=self.root/'results';lock=f.read(definition/'definition_lock.json')
        with patch.object(f,'verify_definition',return_value=lock),patch.object(f,'model_preflight',return_value={}):
            # Empty orphan folder represents a process killed before its first manifest.
            (out/'attempts'/f"{entry['experiment_id']}_a1").mkdir(parents=True)
            registration=f.metrics.register(out)
            write_json(out/'execution_registration.json',dict(definition_sha256=f.digest(definition/'definition_lock.json')))
            r=f.execute(definition,out,max_runs=1)
            self.assertEqual(r['valid_replications'],1);self.assertEqual(r['attempts'],2)
            with patch.object(f,'run_experiment') as run:r=f.execute(definition,out,max_runs=1)
            run.assert_not_called()
        self.assertEqual(r['attempt_records'][1]['seed'],101)
        self.assertEqual(r['attempt_records'][1]['attempt'],2)
        self.assertEqual(r['attempt_records'][0]['exclusion_reasons'],['missing_or_corrupt_artifacts'])

    def test_exhausted_seed_remains_missing_not_replaced(self):
        entry=self.entry();definition=self.synthetic_definition(entry);out=self.root/'results'
        for i in (1,2):(out/'attempts'/f"{entry['experiment_id']}_a{i}").mkdir(parents=True)
        r=f.summarize(definition,out,verify=False)
        self.assertFalse(r['exit_criterion_passed']);self.assertEqual(r['valid_replications'],0)
        self.assertEqual(next(iter(r['cells'].values()))['exhausted_seeds'],[101])

    def test_decision_audit_accepts_explicit_timeout_and_malformed_response_fallback(self):
        root=self.root/'audit';agent=root/'Drone1';agent.mkdir(parents=True)
        policy=self.pilot['model'];mission={'vehicles':{'Drone1':{}}}
        def lines(name,rows):
            (agent/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows))
        prompts=[dict(request_id='Drone1:1',prompt='{}'),dict(request_id='Drone1:2',prompt='{}')]
        lines('prompts',prompts)
        lines('request_specs',[dict(request_id=p['request_id'],model_digest=policy['model_digest'],
            request=dict(model=policy['model'],messages=[{'role':'user','content':'{}'}],options={'temperature':0,'seed':101})) for p in prompts])
        lines('responses',[dict(token='Drone1:1',raw='malformed JSON',simulation_time_s=2)])
        lines('decision_history',[dict(event='policy_error',time_s=2,reason_code='invalid_json'),
            dict(event='deterministic_fallback',time_s=2),dict(event='inference_timeout',time_s=3,request_id='Drone1:2')])
        self.assertEqual(f.decision_audit(root,mission,policy,101),[])
        lines('decision_history',[])
        self.assertIn('incomplete_decision_audit',f.decision_audit(root,mission,policy,101))

    def test_validation_derived_from_raw_runs_ignores_edited_ready_flag(self):
        entry=self.entry();validation=self.root/'validation';validation.mkdir()
        c=copy.deepcopy(self.c);c.update(architectures=['A'],conditions=['nominal'],failure_profiles=['none'])
        write_json(validation/'validation_definition.json',dict(design=c,design_sha256=f.sha(c),source_sha256=f.source_hashes()))
        write_json(validation/'batch.json',dict(experiments=[entry]))
        write_json(validation/'validation_report.json',dict(eligible_for_main=True))
        report=f.write_validation_report(validation)
        self.assertFalse(report['eligible_for_main'])
        self.assertTrue(any(b.startswith('technical_invalid:') for b in report['blockers']))

    def test_corrupt_manifest_types_do_not_crash_batch_accounting(self):
        entry=self.entry();folder=self.root/'corrupt';(folder/'run').mkdir(parents=True)
        write_json(folder/'manifest.json',[]);write_json(folder/'run/summary.json',{})
        write_json(folder/'run/manifest.json',{})
        assessment=f.assess_attempt(folder,entry,f.source_hashes())
        self.assertFalse(assessment['technical_valid'])
        self.assertIn('missing_or_corrupt_artifacts',assessment['exclusion_reasons'])

    def test_user_interrupt_preserves_attempt_and_stops_instead_of_running_next_case(self):
        entry=self.entry();definition=self.synthetic_definition(entry);out=self.root/'results'
        lock=f.read(definition/'definition_lock.json')
        def interrupted(current,root,*args):
            (root/current['experiment_id']).mkdir()
            return {'status':'interrupted'}
        with patch.object(f,'verify_definition',return_value=lock),patch.object(f,'model_preflight',return_value={}),patch.object(f,'run_experiment',side_effect=interrupted) as run:
            report=f.execute(definition,out)
        self.assertEqual(run.call_count,1)
        self.assertFalse(report['exit_criterion_passed'])
        self.assertEqual(report['attempts'],1)

    def test_definition_hash_changes_are_rejected(self):
        root=self.root/'definition';root.mkdir();p=root/'design.json';write_json(p,self.c)
        write_json(root/'definition_lock.json',dict(phase17_root=str(self.root/'pilot'),phase17_lock_sha256='x',source_sha256=f.source_hashes(),validation_evidence_sha256={},files_sha256={'design.json':f.digest(p)}))
        pilot=self.root/'pilot';pilot.mkdir();(pilot/'freeze_manifest.json').write_text('x')
        lock=f.read(root/'definition_lock.json');lock['phase17_lock_sha256']=f.digest(pilot/'freeze_manifest.json');write_json(root/'definition_lock.json',lock)
        with patch.object(f,'verify_frozen',return_value={}):
            f.verify_definition(root);p.write_text(p.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'definition changed'):f.verify_definition(root)


if __name__=='__main__':unittest.main()
