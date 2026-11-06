import copy
from dataclasses import replace
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentic_uav.experiments import pilot_v2_runner as runner
from agentic_uav.experiments.pilot_resilience_v2 import OwnVehicleTelemetry,owned_motion_trigger,agent_class,settings
from agentic_uav.experiments.architectures import ComparisonAgent,BID_WEIGHTS
from agentic_uav.experiments.resilience import ReachablePeerGuardian,settings as resilience_settings
from agentic_uav.experiments import metrics
from agentic_uav.control.runtime_guardian import Action,Config,State,RuntimeGuardian
from agentic_uav.control.scenario_manager import ExperimentSchedule
from agentic_uav.coordination.contract_net import TaskStatus
from agentic_uav.policy.mission import load_mission


class Phase17V2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.config=json.loads(Path('configs/phase17/resilience_v2.json').read_text())

    def test_small_stages_and_protected_seeds(self):
        for stage,count in [('smoke',2),('focused',4),('severe',4)]:
            out=self.root/stage;out.mkdir()
            batch=runner.build(self.config,out,stage,4,7,'pinned','alive','owned_motion')
            self.assertEqual(len(batch['experiments']),count)
            for e in batch['experiments']:
                self.assertEqual(e['settings']['ticks']*e['settings']['dt'],240)
                self.assertEqual(e['settings']['pilot_resilience_v2']['fault_mode'],'owned_motion')
        out=self.root/'protected';out.mkdir()
        with self.assertRaises(ValueError):runner.build(self.config,out,'smoke',4,101,'replay','alive','owned_motion')
        self.assertFalse((out/'fixtures').exists())

    def test_telemetry_has_no_task_heartbeat_or_synthetic_freshness(self):
        sent=[];service=OwnVehicleTelemetry(lambda *a:sent.append(a),['Drone2'],.5)
        sample=dict(position=[1,2,-3],velocity=[0,0,0],battery=80,role='SCOUT',observed_at=1.)
        self.assertTrue(service.tick(2.,**sample));self.assertFalse(service.tick(2.1,**sample))
        self.assertTrue(service.tick(2.6,**sample))
        self.assertEqual(len(sent),2)
        self.assertTrue(all(row[0].value=='STATUS_UPDATE' for row in sent))
        self.assertEqual(sent[1][1]['observed_at'],1.)
        self.assertNotIn('task_id',sent[0][1]);self.assertNotIn('alive',sent[0][1])

    def test_state_trigger_waits_for_owned_real_motion_and_fixed_time_unchanged(self):
        actor=SimpleNamespace(agent_id='Drone1',position=[0,0,-3],velocity=[0,0,0],tasks={})
        gate=SimpleNamespace(active={});c=settings({'enabled':True})
        predicate=owned_motion_trigger(actor,gate,c,(0,0,-3));schedule=ExperimentSchedule('Drone1',5);schedule.trigger=predicate
        self.assertEqual(schedule.advance(100),[])
        actor.tasks['A']=SimpleNamespace(status=TaskStatus.ASSIGNED,assigned_agent='Drone1')
        gate.active['Drone1']=Action('test','Drone1','MOVE',0,200,((6,0,-3),),1)
        actor.position=[1,0,-3];self.assertEqual(schedule.advance(101),[])
        actor.velocity=[1,0,0];self.assertEqual(schedule.advance(102),['Drone1'])
        self.assertEqual(schedule.advance(103),[])
        original=ExperimentSchedule('Drone1',8);self.assertEqual(original.advance(7.9),[]);self.assertEqual(original.advance(8),['Drone1'])

    def test_static_cost_checks_separate_commands_and_cumulative_battery(self):
        mission=self.config['pilot_template']['mission_source'];m,c,tasks,routes=load_mission(mission)
        routes[tasks[0].task_id]=[[6,0,-3],[12,0,-3],[12,3,-3],[6,3,-3]]
        cls=agent_class(ComparisonAgent);a=object.__new__(cls)
        a.agent_id='Drone2';a.routes=routes;a.checkpoints={};a.position=[6,27,-3];a.battery=80
        a.communication_risk=0;a.capabilities={'search'};a.weights=BID_WEIGHTS;a.calculations={};a.status_times={};a.peers=[]
        a.workload=lambda:0
        a.guardian=ReachablePeerGuardian(c,resilience_settings({'enabled':True}),.2)
        a.safety_state=lambda now:State('Drone2',tuple(a.position),now,a.battery,(0,8,-3))
        whole=Action('whole','Drone2','MOVE',0,30,tuple(tuple(p) for p in routes[tasks[0].task_id]),1)
        self.assertIn('execution_deadline',RuntimeGuardian._route_errors(a.guardian,whole,a.safety_state(0),0))
        result=a._cost(tasks[0],0)
        self.assertTrue(result['route_feasible']);self.assertGreater(result['travel_time_s'],30)
        a.battery=c.min_battery_reserve_percent+.1
        self.assertFalse(a._cost(tasks[0],0)['battery_sufficient'])
        a.routes[tasks[0].task_id]=[[100,0,-3]]
        self.assertFalse(a._cost(tasks[0],0)['full_route_static_feasible'])

    def test_smoke_recovery_and_lossless_metrics_round_trip(self):
        report=runner.execute('configs/phase17/resilience_v2.json',self.root/'smoke',stage='smoke')
        self.assertEqual(report['successful_missions'],2)
        fault=next(r for r in report['rows'] if r['fault_observed'])
        self.assertTrue(fault['fault_owned']);self.assertTrue(fault['fault_during_move'])
        self.assertIsNotNone(fault['replacement_s']);self.assertGreater(fault['replacement_s'],fault['fault_s'])
        self.assertIsNotNone(fault['productive_resume_s']);self.assertEqual(fault['sampled_separation_violations'],0)
        self.assertTrue(fault['all_dispatched_actions_guarded']);self.assertLess(fault['time_s'],240)
        self.assertLess(report['stored_bytes'],10*1024**2)
        folder=self.root/'smoke/runs'/fault['experiment_id'];before=metrics.evaluate_run(folder)
        events=metrics.Evidence(folder).read('events.jsonl')
        sent=[e for e in events if e['event_type']=='MESSAGE_SENT']
        physical=[e for e in sent if e['agent_id']=='Drone1' and e['simulation_time_s']>fault['fault_s']]
        self.assertTrue(any(e['data']['envelope']['message_type']=='STATUS_UPDATE' for e in physical))
        self.assertFalse(any(e['data']['envelope']['message_type']=='HEARTBEAT' for e in physical))
        self.assertTrue(any(e['data']['envelope']['payload'].get('completed_tasks') for e in sent))
        self.assertFalse((folder/'events.jsonl').exists());self.assertTrue((folder/'traces.zip').exists())
        restored=runner.restore_evidence(folder);self.assertGreater(restored['restored_files'],0)
        self.assertEqual(metrics.evaluate_run(folder),before)
        index=json.loads((folder/'evidence_archives.json').read_text())
        archive=folder/index['archives'][0]['archive'];archive.write_bytes(archive.read_bytes()+b'bad')
        with self.assertRaises(ValueError):runner.restore_evidence(folder)

    def test_full_silence_keeps_uncertainty_and_cannot_claim_telemetry_recovery(self):
        # Same guardian and new schedule; the telemetry ablation must still fail closed.
        cfg=copy.deepcopy(self.config);cfg['duration_s']=120
        p=self.root/'short.json';p.write_text(json.dumps(cfg))
        report=runner.execute(p,self.root/'silent',stage='smoke',telemetry='silent')
        fault=next(r for r in report['rows'] if r['fault_observed'])
        self.assertFalse(fault['mission_complete']);self.assertIsNone(fault['replacement_s'])
        self.assertTrue(fault['all_dispatched_actions_guarded']);self.assertEqual(fault['sampled_separation_violations'],0)

    def test_model_failure_is_preserved_before_run_without_replay_substitution(self):
        with patch.object(runner.OllamaProvider,'verify',side_effect=RuntimeError('server unavailable')),patch.object(runner,'run_experiment') as run:
            with self.assertRaises(RuntimeError):runner.execute('configs/phase17/resilience_v2.json',self.root/'pinned',stage='focused')
        run.assert_not_called();self.assertTrue((self.root/'pinned/preflight_error.json').exists())
        self.assertTrue((self.root/'pinned/batch.json').exists())


if __name__=='__main__':unittest.main()
