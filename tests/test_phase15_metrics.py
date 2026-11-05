import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentic_uav.experiments import comparison
from agentic_uav.experiments.event_logging import EventLog, instrument
from agentic_uav.experiments.metrics import (work_metrics,communication_metrics,safety_metrics,recovery_metrics,
    additional_components,diagnostic_metrics,match_continuity,evaluate_batch,evaluate_run,Evidence,contract)
from agentic_uav.experiments.runner import run_batch


def event(event_type,time=0,agent='Drone1',**data):
    return dict(event_type=event_type,simulation_time_s=time,agent_id=agent,data=data)


class MetricUnitTests(unittest.TestCase):
    def test_unsupported_metric_modes_and_invalid_windows_are_rejected(self):
        import agentic_uav.experiments.metrics as metrics
        original=contract()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'policy.json'
            for key,value in [('mission_score_mode','invented_weighted_score'),('role_return_window_s',-1)]:
                bad=dict(original);bad[key]=value;path.write_text(json.dumps(bad))
                with patch.object(metrics,'CONTRACT_PATH',path):
                    with self.assertRaises(ValueError):contract()

    def test_unique_work_duplicate_work_and_zero_denominator(self):
        arrivals=[dict(task_id='A',index=i) for i in (0,0,1)]+[dict(task_id='other',index=0)]
        m=work_metrics(arrivals,{('A',0),('A',1)})
        self.assertEqual(m['unique_productive_work'],2);self.assertEqual(m['repeated_required_work'],1)
        self.assertEqual(m['coordination_efficiency'],.5);self.assertEqual(m['route_work_fraction'],1)
        self.assertIsNone(work_metrics([],{('A',0)})['coordination_efficiency'])
        with self.assertRaises(ValueError):work_metrics([dict(task_id='A',index=True)],{('A',0)})

    def test_communication_counts_broadcast_retries_expiry_and_future_egress(self):
        rows=[]
        for mid,recipient,status,time in [('m:tx:1','a','delivered',0),('m:tx:1','b','dropped',0),
            ('m:tx:2','a','delivered',.2),('m:tx:2','b','expired',.2),('future','a','queued',10)]:
            rows.append(dict(message_id=mid,recipient_id=recipient,status=status,size_bytes=10,
                transmission_time=time,sent_time=0,actual_delivery_time=time if status=='delivered' else None))
        m=communication_metrics(rows,2,2)
        self.assertEqual(m['unique_message_sends'],3);self.assertEqual(m['recipient_packet_attempts'],5)
        self.assertEqual(m['bytes_transmitted'],40);self.assertEqual(m['attempted_bytes'],50)
        self.assertEqual(m['retry_message_sends'],1);self.assertEqual(m['duplicate_transport_deliveries'],1)
        self.assertEqual(m['messages_per_completed_task'],1.5);self.assertEqual(m['expired_messages'],1)
        self.assertEqual(m['pending_messages'],1)
        self.assertIsNone(communication_metrics(rows,2,0)['messages_per_completed_task'])

    def test_safety_counts_samples_episodes_and_routine_modifications_separately(self):
        flight=[]
        for t,distance in enumerate((1,1,3,1)):
            flight.extend([dict(time_s=t,agent_id='a',position=[0,0,-3]),dict(time_s=t,agent_id='b',position=[distance,0,-3])])
        audit=[dict(outcome=o,reasons=r,fallback=f,selected_action={} if f else None) for o,r,f in [
            ('APPROVE',[],None),('APPROVE_WITH_MODIFICATION',['bounded_motion_segment'],None),
            ('REJECT_AND_REPLAN',['geofence'],None),('EXECUTE_SAFE_FALLBACK',['battery_reserve'],'RETURN_HOME')]]
        # A selected action is a nonempty execution candidate, not an empty placeholder.
        audit[-1]['selected_action']={'kind':'RETURN_HOME'}
        telemetry=[event('OBSERVATION_RECEIVED',t,source='own_telemetry',observation={'collision':value}) for t,value in enumerate((False,True,True))]
        m=safety_metrics(flight,audit,dict(min_separation_m=2),telemetry)
        self.assertEqual(m['sampled_separation_violations'],3);self.assertEqual(m['separation_violation_episodes'],2)
        self.assertEqual(m['collisions'],1);self.assertEqual(m['guardian_interventions'],3)
        self.assertEqual(m['routine_segment_modifications'],1);self.assertEqual(m['corrective_guardian_interventions'],2)
        self.assertEqual(m['unsafe_proposal_evaluations'],2);self.assertEqual(m['emergency_fallbacks'],1)

    def test_restricted_zone_crossing_and_absent_sensors_are_not_conflated(self):
        flight=[dict(time_s=t,agent_id='a',position=[x,0,-3]) for t,x in [(0,-2),(1,2)]]
        m=safety_metrics(flight,[],dict(keepouts=[dict(x_min=-1,x_max=1,y_min=-1,y_max=1,z_min=-4,z_max=-2)]),[])
        self.assertEqual(m['restricted_zone_entries_sampled'],0);self.assertEqual(m['restricted_zone_crossings_inferred'],1)
        self.assertIsNone(m['collisions']);self.assertIsNone(m['sampled_separation_violations'])
        self.assertIsNone(safety_metrics(None,None,{},[])['guardian_interventions'])

    def test_unverifiable_peer_state_is_not_counted_as_proven_unsafe_proposal(self):
        m=safety_metrics(None,[dict(outcome='REJECT_AND_REPLAN',reasons=['stale_or_future_peer_belief'])],{},[])
        self.assertEqual(m['guardian_interventions'],1);self.assertEqual(m['unsafe_proposal_evaluations'],0)
        self.assertEqual(m['unverifiable_state_rejections'],1)

    def test_recovery_filters_peer_acknowledgments_and_repeated_work(self):
        events=[event('TASK_ASSIGNED',0,'Drone1',task_id='A',owner='Drone1',version=1),
            event('TASK_ASSIGNED',2,'Drone2',task_id='A',owner='Drone1',version=1),
            event('FAULT_INJECTED',3,'Drone1'),event('TASK_ASSIGNED',6,'Drone2',task_id='A',owner='Drone2',version=2)]
        arrivals=[dict(task_id='A',index=0,time_s=1,agent_id='Drone1'),dict(task_id='A',index=0,time_s=7,agent_id='Drone2'),
            dict(task_id='A',index=1,time_s=9,agent_id='Drone2')]
        m=recovery_metrics(events,arrivals,[],[],10)[0]['tasks'][0]
        self.assertEqual(m['recovery_time_s'],3);self.assertEqual(m['productive_resume_time_s'],6)
        m=recovery_metrics(events[:3],arrivals[:1],[],[],10)[0]['tasks'][0]
        self.assertIsNone(m['recovery_time_s']);self.assertTrue(m['acceptance_censored'])

    def test_fault_with_no_owned_task_is_not_instant_recovery(self):
        m=recovery_metrics([event('FAULT_INJECTED',2)],[],[],[],10)[0]
        self.assertEqual(m['applicability'],'no_owned_unfinished_task_at_onset');self.assertEqual(m['tasks'],[])

    def test_partition_resumption_requires_previously_active_motion_interruption(self):
        partition=dict(start_s=3,end_s=5,groups=[['Drone1'],['Drone2']])
        events=[event('GUARDIAN_INTERVENED',4,audit=dict(reasons=['stale_or_future_peer_belief']))]
        arrivals=[dict(task_id='A',index=0,time_s=8,agent_id='Drone1')]
        m=recovery_metrics(events,arrivals,[],[partition],10)[0]
        self.assertFalse(m['interruption_observed']);self.assertIsNone(m['productive_resume_time_s'])
        events=[event('SKILL_STARTED',2,command_id='move',kind='MOVE'),event('SKILL_CANCELLED',4,command_id='move')]+events
        m=recovery_metrics(events,arrivals,[],[partition],10)[0]
        self.assertTrue(m['interruption_observed']);self.assertEqual(m['productive_resume_time_s'],5)
        self.assertIsNone(m['recovery_time_s'])

    def test_components_require_real_observations_or_initialized_sensors(self):
        mission=dict(search_cells=['a','b'],target_ids=['T1'],requires_safe_return=True,vehicles={'Drone1':{}})
        m=additional_components([],mission)
        self.assertIsNone(m['area_coverage_fraction']);self.assertIsNone(m['target_detection_fraction'])
        events=[event('SEARCH_CELL_OBSERVED',cell_id='a'),event('SEARCH_CELL_OBSERVED',cell_id='a'),
            event('TARGET_FOUND',target_id='T1'),event('TARGET_DETECTED',target_id='T1',verified=True),
            event('SAFE_RETURN_VERIFIED',verified=True)]
        m=additional_components(events,mission)
        self.assertEqual(m['area_coverage_fraction'],.5);self.assertEqual(m['redundant_cell_observations'],1)
        self.assertEqual(m['target_detection_fraction'],1);self.assertEqual(m['safe_return_fraction'],1)
        self.assertIsNone(additional_components([event('TARGET_FOUND',target_id='T1')],mission)['target_detection_fraction'])

    def test_continuity_is_paired_and_zero_reference_is_undefined(self):
        def row(identifier,condition,score,work,key='same'):
            return dict(experiment_id=identifier,network_profile=condition,match_key=key,evidence_issues=[],
                primary=dict(mission=dict(mission_score=score,components=dict(route_work_fraction=work)),continuity_retention={}))
        a=row('nominal','nominal',1,1);b=row('severe','severe',0,.5);other=row('other','moderate',1,1,'other')
        match_continuity([a,b,other]);self.assertEqual(b['primary']['continuity_retention']['value'],0)
        self.assertEqual(b['primary']['continuity_retention']['route_work_retention'],.5)
        self.assertEqual(other['primary']['continuity_retention']['reason'],'no_matched_nominal')
        a['primary']['mission']['mission_score']=0;match_continuity([a,b])
        self.assertIsNone(b['primary']['continuity_retention']['value'])
        self.assertEqual(b['primary']['continuity_retention']['reason'],'nominal_score_zero_or_unknown')

    def test_partial_usage_is_not_estimated_and_oscillations_are_only_candidates(self):
        events=[event('LLM_CALLED'),event('LLM_CALLED'),event('LLM_USAGE',prompt_eval_count=40,eval_count=10)]
        history=[dict(event='role_changed',agent_id='a',time_s=1,previous='SCOUT',role='RELAY'),
            dict(event='role_changed',agent_id='a',time_s=2,previous='RELAY',role='SCOUT'),
            dict(event='policy_error',reason_code='invalid_json'),dict(event='policy_error',reason_code='unsafe_action:geofence')]
        m=diagnostic_metrics(events,history,[],None,{},set(),set(),10,{},dict())
        self.assertFalse(m['token_usage']['complete']);self.assertIsNone(m['token_usage']['input_tokens'])
        self.assertEqual(m['token_usage']['reported_input_token_subtotal'],40)
        self.assertEqual(m['role_oscillation_candidates'],1);self.assertIsNone(m['unnecessary_role_oscillations'])
        self.assertEqual(m['invalid_structured_outputs'],1)

    def test_reported_usage_hook_preserves_provider_response_and_ignores_late_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'events.jsonl';log=EventLog(path,'test','test')
            provider=comparison.OllamaProvider
            response=dict(prompt_eval_count=12,eval_count=7,message=dict(content='{}'))
            request=dict(model='test:pinned',messages=[dict(role='user',content=json.dumps(dict(agent_id='Drone1',own_state=dict(time_s=2))))])
            with patch.object(provider,'_http',return_value=response):
                with instrument(comparison,log):
                    instance=comparison.OllamaProvider('test:pinned','a'*64)
                    self.assertEqual(instance._http('/api/chat',request),response)
                    log.seal();instance._http('/api/chat',request)
            records=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records),1);self.assertEqual(records[0]['event_type'],'LLM_USAGE')
            self.assertEqual(records[0]['data']['prompt_eval_count'],12)
            self.assertEqual(records[0]['data']['eval_count'],7)

    def test_orphaned_tasks_use_complete_live_owner_snapshots_and_keep_conflicts(self):
        snapshots={a:event('TASK_STATE_SNAPSHOT',10,a,tasks=[dict(task_id='A',status='assigned',assigned_agent=a,lease_expires_at=20)]) for a in ('a','b')}
        c=dict(initial_assignments={'a':['A'],'b':['B']})
        m=diagnostic_metrics([],[],[],None,snapshots,{'A','B'},set(),10,c,{})
        self.assertEqual(m['orphaned_tasks_at_end'],1);self.assertEqual(m['multiple_self_declared_owners_at_end'],1)
        del snapshots['b']
        self.assertIsNone(diagnostic_metrics([],[],[],None,snapshots,{'A','B'},set(),10,c,{})['orphaned_tasks_at_end'])

    def test_initialized_sensor_can_report_genuine_zero(self):
        mission=dict(search_cells=['a','b'],target_ids=['T1'],requires_safe_return=True,vehicles={'Drone1':{}})
        events=[event('SENSOR_INITIALIZED',sensor=s) for s in ('area_coverage','target_detection','safe_return')]
        m=additional_components(events,mission)
        self.assertEqual(m['area_coverage_fraction'],0);self.assertEqual(m['target_detection_fraction'],0)
        self.assertEqual(m['safe_return_fraction'],0)

    def test_distance_and_simulated_battery_do_not_become_joules(self):
        telemetry=[event('OBSERVATION_RECEIVED',t,source='own_telemetry',observation=dict(battery=b)) for t,b in [(0,80),(1,79.5)]]
        flight=[dict(time_s=t,agent_id='Drone1',position=p) for t,p in [(0,[0,0,0]),(1,[3,4,0])]]
        m=diagnostic_metrics(telemetry,[],[],flight,{},set(),set(),1,{},dict())
        self.assertEqual(m['distance_travelled_m'],5);self.assertEqual(m['battery_decrease_percent_by_agent']['Drone1'],.5)
        self.assertIsNone(m['energy_joules'])


class MetricIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.entry=dict(experiment_id='nominal',architecture='deterministic_decentralized',scenario='four_sector_search',team_size=4,
            network_profile='nominal',failure_profile='none',random_seed=42,planner='deterministic',
            settings=dict(ticks=200,dt=.1,clock_mode='simulated',bid_window=.5,lease_seconds=10,beacon_interval_s=.2))
    def batch(self,entries,evaluate=True,name='results'):
        source=self.root/(name+'.json');source.write_text(json.dumps(dict(schema_version=1,experiments=entries)))
        return run_batch(source,self.root/name,evaluate=evaluate),self.root/name
    def read(self,path):return json.loads(path.read_text())

    def test_combined_phase14_phase15_registers_before_run_and_exports_metrics(self):
        degraded=copy.deepcopy(self.entry);degraded.update(experiment_id='moderate',network_profile='moderate')
        failed=copy.deepcopy(self.entry);failed.update(experiment_id='failure',failure_profile='drone_failure_midmission')
        failed['settings']['scenario']=dict(fail_agent='Drone1',fail_at_s=1)
        result,root=self.batch([self.entry,degraded,failed])
        self.assertTrue(result['evaluation']['prespecified']);self.assertEqual(result['evaluation']['experiments_evaluated'],3)
        self.assertEqual(result['evaluation']['evidence_issues'],0)
        nominal=self.read(root/'metrics/nominal.metrics.json');failure=self.read(root/'metrics/failure.metrics.json')
        self.assertTrue(nominal['primary']['mission']['success']);self.assertGreater(nominal['primary']['completion_time']['value_s'],0)
        self.assertEqual(failure['primary']['completion_time']['status'],'timeout');self.assertIsNone(failure['primary']['completion_time']['value_s'])
        self.assertTrue(failure['primary']['completion_time']['censored']);self.assertIsNone(nominal['primary']['safety']['collisions'])
        self.assertIsNotNone(nominal['diagnostic']['battery_decrease_percent_by_agent'])
        m=self.read(root/'metrics/moderate.metrics.json')
        self.assertEqual(m['primary']['continuity_retention']['nominal_experiment_id'],'nominal')
        self.assertTrue((root/'metric_contract.json').exists());self.assertTrue((root/'metrics/metrics.csv').exists())

    def test_preflight_failures_are_not_fast_completions_and_reanalysis_is_retrospective(self):
        bad=copy.deepcopy(self.entry);bad.update(experiment_id='bad',team_size=3)
        result,root=self.batch([bad],False)
        analysis=evaluate_batch(root,self.root/'retrospective')
        m=self.read(self.root/'retrospective/bad.metrics.json')
        self.assertFalse(analysis['prespecified']);self.assertEqual(m['primary']['completion_time']['status'],'not_started')
        self.assertIsNone(m['primary']['completion_time']['value_s']);self.assertIsNone(m['primary']['mission']['mission_score'])

    def test_missing_arrival_cannot_inherit_summary_success(self):
        _,root=self.batch([self.entry],False)
        path=root/'nominal/run/waypoint_arrivals.json';arrivals=self.read(path);path.write_text(json.dumps(arrivals[:-1]))
        m=evaluate_run(root/'nominal');self.assertFalse(m['primary']['mission']['success'])
        self.assertTrue(m['evidence_issues']);self.assertIsNone(m['primary']['completion_time']['value_s'])

    def test_corrupt_case_does_not_discard_other_results(self):
        second=copy.deepcopy(self.entry);second['experiment_id']='second'
        _,root=self.batch([self.entry,second],False)
        (root/'nominal/manifest.json').write_text('{bad')
        summary=evaluate_batch(root,self.root/'review')
        self.assertEqual(summary['experiments_evaluated'],2);self.assertGreater(summary['evidence_issues'],0)
        self.assertTrue(self.read(self.root/'review/second.metrics.json')['primary']['mission']['success'])

    def test_running_manifest_not_appended_to_batch_still_gets_evaluated(self):
        _,root=self.batch([self.entry],False)
        batch=self.read(root/'batch_manifest.json');batch['runs']=[];(root/'batch_manifest.json').write_text(json.dumps(batch))
        summary=evaluate_batch(root,self.root/'review');self.assertEqual(summary['experiments_evaluated'],1)

    def test_truncated_last_jsonl_record_keeps_earlier_records_and_flags_evidence(self):
        folder=self.root/'evidence';folder.mkdir();(folder/'events.jsonl').write_text('{"ok":1}\n{"partial":')
        e=Evidence(folder);self.assertEqual(e.read('events.jsonl'),[dict(ok=1)]);self.assertTrue(e.issues)


if __name__=='__main__':unittest.main()
