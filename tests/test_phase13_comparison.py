"""Authority isolation, matched inputs and shared safety for the comparison runner."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentic_uav.experiments.comparison import configuration,run_comparison,effective_network
from agentic_uav.experiments.architectures import ComparisonAgent,FixedTaskAgent,FleetController,RulePolicy,CONTROLLER
from agentic_uav.comm.protocol import PerfectMessageBus,AgentMessage,MessageType as MT
from agentic_uav.comm.degraded import ObservedEndpoint,DegradedMessageBus
from agentic_uav.policy.mission import load_mission
from agentic_uav.policy.structured import ReplayProvider,OllamaProvider,PolicyError,ModelIdentityError,decision_example
from agentic_uav.control.runtime_guardian import RuntimeGuardian,GuardedExecutor
from agentic_uav.coordination.contract_net import TaskStatus
from agentic_uav.control.scenario_manager import ExperimentSchedule


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.counter=0;self.m,self.gc,self.tasks,self.routes=load_mission('configs/phase12/mission.example.json')
        self.clock=[0.];self.ids=list(self.m['vehicles']);self.bus=PerfectMessageBus(self.ids+[CONTROLLER],lambda:self.clock[0])
        self.settings=dict(persistent_memory=True,dynamic_roles=True,task_leases=True,beacon_interval_s=.2,command_timeout_s=2,
            state_timeout_s=2,horizon_s=30,lease_seconds=5,bid_window=.5)

    def run_case(self,architecture='C',**overrides):
        self.counter+=1
        c=dict(architecture=architecture,ticks=200,dt=.1,lease_seconds=10,bid_window=.5,
            beacon_interval_s=.2,decision_interval=.2,output_dir=str(Path(self.tmp.name)/str(self.counter)))
        c.update(overrides)
        summary=run_comparison(c)
        self.assertIsNone(summary['error'])
        return summary,Path(c['output_dir'])

    def agent(self,architecture='D',aid='Drone1',settings=None):
        v=self.m['vehicles'][aid];cls=FixedTaskAgent if architecture in ('A','B') else ComparisonAgent
        endpoint=ObservedEndpoint(self.bus.endpoint(aid),aid,lambda:self.clock[0])
        opts=dict(initial_task_ids=['SEARCH_SECTOR_A'],horizon=30) if architecture=='B' else {}
        a=cls(aid,[p for p in self.ids if p!=aid],endpoint,self.tasks,v['start_position'],
            role=v['role'],routes=self.routes,home=v['home'],relay_point=self.m['relay_point'],guardian=RuntimeGuardian(self.gc),
            output_dir=self.tmp.name,provider=RulePolicy() if architecture in ('A','C') else ReplayProvider(),mission=self.m['mission'],
            architecture=architecture,settings=settings or self.settings,initial_roles={i:self.m['vehicles'][i]['role'] for i in self.ids},
            lease_s=5,bid_window=.5,**opts)
        return a

    def test_all_four_selected_architectures_complete_nominal_with_shared_inputs(self):
        fingerprints=[]
        for architecture in 'ABCD':
            summary,out=self.run_case(architecture)
            self.assertTrue(summary['mission_complete'],architecture)
            self.assertTrue(summary['mission_execution_success'])
            self.assertEqual(summary['decentralized_coordination_enabled'],architecture in ('C','D'))
            self.assertEqual(len(summary['completed_task_ids']),4)
            self.assertEqual(summary['duplicate_task_completions'],0)
            self.assertTrue(summary['all_dispatched_actions_guarded'])
            self.assertFalse(summary['llm_inference']);self.assertFalse(summary['llm_exit_criterion_observed'])
            manifest=json.loads((out/'manifest.json').read_text());fingerprints.append(manifest['shared_inputs_sha256'])
            self.assertEqual(manifest['guardian'],'Phase11 RuntimeGuardian + GuardedExecutor')
            if architecture=='B':
                self.assertTrue(manifest['task_lease_expiry_disabled'])
                self.assertTrue(all(m['message_type'] in ('HEARTBEAT','STATUS_UPDATE') for m in json.loads((out/'messages.json').read_text())))
                self.assertEqual(summary['lease_expirations'],0)
            if architecture=='A':
                self.assertFalse(any(m['message_type']=='TASK_BID' for m in json.loads((out/'messages.json').read_text())))
                self.assertTrue(json.loads((out/'controller_events.json').read_text()))
            if architecture=='C':self.assertEqual(summary['provider'],'deterministic')
        self.assertEqual(len(set(fingerprints)),1)

    def test_independent_agent_ignores_all_peer_allocation_commands(self):
        a=self.agent('B');self.clock[0]=1
        message=AgentMessage('peer_award',MT.TASK_AWARD,'Drone2',['Drone1'],'phase8',1,1,5,
            dict(task_id='SEARCH_SECTOR_B',version=1,owner='Drone2',score=0))
        self.bus.endpoint('Drone2').send(message);a.receive(1)
        self.assertIsNone(a.tasks['SEARCH_SECTOR_B'].assigned_agent)
        with self.assertRaises(PolicyError):a.apply(decision_example('announce_task',dict(task_id='SEARCH_SECTOR_B')),1,None)
        self.assertEqual(a.tasks['SEARCH_SECTOR_A'].assigned_agent,'Drone1')

    def test_controller_cannot_assign_from_undelivered_state(self):
        controller=FleetController(self.bus.endpoint(CONTROLLER),self.tasks,self.ids,self.settings)
        controller.step(0);self.assertFalse(controller.events)
        self.clock[0]=1
        self.bus.endpoint('Drone1').send(AgentMessage('state',MT.STATUS_UPDATE,'Drone1',[CONTROLLER],'phase8',1,1,5,
            dict(position=[0,0,-3],role='SCOUT',battery=80,observed_at=1)))
        controller.step(1);self.assertFalse(controller.events)
        controller.receive(1);controller.step(1)
        self.assertEqual(sum(e['event']=='central_assignment' for e in controller.events),1)

    def test_delivered_state_but_lost_central_commands_trigger_local_fallback(self):
        original=DegradedMessageBus._blocked
        def blocked(bus,sender,recipient,now):
            return 'test_downlink_loss' if sender==CONTROLLER else original(bus,sender,recipient,now)
        with patch.object(DegradedMessageBus,'_blocked',blocked):s,out=self.run_case('A',ticks=80)
        self.assertFalse(s['mission_complete'])
        self.assertGreater(sum(s['fallbacks_by_agent'].values()),0)
        self.assertGreater(s['network_drop_reasons']['test_downlink_loss'],0)
        self.assertTrue(any(e['event']=='central_assignment' for e in json.loads((out/'controller_events.json').read_text())))
        self.assertFalse(any(e['kind']=='MOVE' for e in json.loads((out/'executed_actions.json').read_text())))

    def test_partitioned_controller_reports_are_not_hidden_global_state(self):
        partitions=[dict(start_s=0,end_s=50,groups=[[CONTROLLER],self.ids])]
        s,out=self.run_case('A',ticks=80,network=dict(partitions=partitions))
        self.assertFalse(s['mission_complete'])
        self.assertFalse(any(e['event']=='central_assignment' for e in json.loads((out/'controller_events.json').read_text())))

    def test_seeded_network_replay_reproduces_actual_message_outcomes(self):
        one,a=self.run_case('C',condition='moderate',seed=17,ticks=140)
        two,b=self.run_case('C',condition='moderate',seed=17,ticks=140)
        self.assertEqual(one,two)
        self.assertEqual(json.loads((a/'messages.json').read_text()),json.loads((b/'messages.json').read_text()))

    def test_c_and_d_have_identical_local_health_inputs_and_tool_candidates(self):
        c=self.agent('C');d=self.agent('D')
        self.clock[0]=1
        # Independently supply the same delivered sensor/message observations.
        for a in (c,d):
            a.state_time=1
            for peer in a.peers:a.peer_beliefs[peer]=dict(position=self.m['vehicles'][peer]['start_position'],velocity=[0,0,0],observed_at=1,battery=80,role='SCOUT')
            a.last_heartbeat={peer:1 for peer in a.peers}
        cc=c.context(1);dc=d.context(1);cc.pop('architecture');dc.pop('architecture')
        self.assertEqual(cc,dc)
        c.memory.append(dict(private='c_only'))
        self.assertNotIn('c_only',json.dumps(d.context(1)))

    def test_memory_ablation_keeps_local_beliefs_and_audit_identity(self):
        settings=dict(self.settings,persistent_memory=False);a=self.agent('D',settings=settings)
        a.memory.append(dict(selected_tool='compute_task_cost',parameters={},result=dict(value='episodic')))
        a.peer_beliefs['Drone2']=dict(position=[0,8,-3],velocity=[0,0,0],observed_at=0,role='SCOUT',battery=80)
        context=a.context(0)
        self.assertEqual(context['memory'],[])
        self.assertIn('Drone2',context['summarized_beliefs']);self.assertEqual(context['agent_id'],'Drone1')
        self.assertTrue(a.memory)  # Audit storage is preserved; episodic prompt input is ablated.

    def test_role_rules_change_a_reserve_without_teleporting(self):
        a=self.agent('C',aid='Drone4');a.role='RESERVE';a.initial_roles['Drone3']='RELAY'
        a.state_time=4;self.clock[0]=4
        for peer in a.peers:
            a.last_heartbeat[peer]=0 if peer=='Drone1' else 4
            a.peer_beliefs[peer]=dict(position=self.m['vehicles'][peer]['start_position'],velocity=[0,0,0],observed_at=4,battery=80,role='RELAY' if peer=='Drone3' else 'SCOUT')
        a.communication_inputs(4);before=list(a.position)
        self.assertEqual(a.role_recommendation(4),('SCOUT','PEER_UNREACHABLE'))
        gate=GuardedExecutor(a.guardian,lambda act:dict(executed=True,completed=True),lambda aid:True)
        a.apply(decision_example('change_role',dict(new_role='SCOUT',reason_code='PEER_UNREACHABLE')),4,gate)
        self.assertEqual(a.role,'SCOUT');self.assertEqual(a.position,before)
        a.settings=dict(a.settings,dynamic_roles=False);a.role='RESERVE'
        self.assertNotIn('change_role',a.context(4)['available_tools'])
        with self.assertRaises(PolicyError):a.apply(decision_example('change_role',dict(new_role='SCOUT',reason_code='PEER_UNREACHABLE')),4,gate)

    def test_initial_beacon_acquisition_does_not_spend_inference_on_missing_peers(self):
        a=self.agent('B');self.assertFalse(a.needs_decision(0))
        for peer in a.peers:a.peer_beliefs[peer]=dict(position=self.m['vehicles'][peer]['start_position'],velocity=[0,0,0],observed_at=.1,role='SCOUT',battery=80)
        self.assertTrue(a.needs_decision(.1))

    def test_initial_relay_is_not_replaced_before_loss_is_observed(self):
        a=self.agent('C',aid='Drone4');a.role='RESERVE';a.initial_roles['Drone3']='RELAY'
        self.assertIsNone(a.role_recommendation(0))
        self.clock[0]=4;a.communication_inputs(4)
        self.assertEqual(a.role_recommendation(4),('RELAY','RELAY_REPLACEMENT'))

    def test_lease_ablation_disables_expiration_for_the_experiment_horizon(self):
        s,out=self.run_case('D',ablations=dict(task_leases=False))
        manifest=json.loads((out/'manifest.json').read_text())
        self.assertIsNone(manifest['effective_task_lease_seconds'])
        self.assertEqual(manifest['lease_deadline_when_disabled_s'],21)
        self.assertEqual(s['lease_expirations'],0)
        _,normal=self.run_case('D')
        normal_packets=json.loads((normal/'messages.json').read_text())
        ablated_packets=json.loads((out/'messages.json').read_text())
        self.assertEqual([m['expires_at']-m['creation_time'] for m in normal_packets],[m['expires_at']-m['creation_time'] for m in ablated_packets])

    def test_failed_task_is_reauctioned_with_leases_but_not_without_them(self):
        config=dict(ticks=120,lease_seconds=3,bid_window=.3,scenario=dict(fail_agent='Drone1',fail_at_s=1))
        normal,out=self.run_case('D',**config)
        ablated,other=self.run_case('D',**config,ablations=dict(task_leases=False))
        events=json.loads((out/'protocol_events.json').read_text())
        off_events=json.loads((other/'protocol_events.json').read_text())
        self.assertTrue(any(e['event']=='lease_expired' and e['task_id']=='SEARCH_SECTOR_A' for e in events))
        self.assertFalse(any(e['event']=='lease_expired' for e in off_events))
        self.assertFalse(normal['mission_complete']);self.assertFalse(ablated['mission_complete'])
        self.assertTrue(normal['all_dispatched_actions_guarded'])

    def test_cli_and_json_select_the_same_architecture_and_ablation(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
        from run_phase13_comparison import parse_configuration
        path=Path(self.tmp.name)/'choice.json';path.write_text(json.dumps(dict(architecture='A')))
        c=parse_configuration(['--config',str(path),'--architecture','D','--without-memory','--condition','moderate'])
        self.assertEqual(c['architecture'],'D');self.assertFalse(c['ablations']['persistent_memory'])
        self.assertEqual(c['condition'],'moderate')

    def test_perfect_communication_ablation_removes_all_degradation(self):
        c=configuration(dict(architecture='D',condition='severe',network=dict(partitions=[dict(start_s=0,end_s=10,groups=[['Drone1'],['Drone2']])]),ablations=dict(perfect_communication=True)))
        network=effective_network(c,self.ids)
        self.assertEqual(network.packet_loss_probability,0);self.assertEqual(network.latency_ms_mean,0)
        self.assertIsNone(network.message_rate_limit);self.assertFalse(network.partitions)

    def test_fallback_replacement_never_calls_a_model_or_claims_llm_evidence(self):
        with patch.object(OllamaProvider,'__init__',side_effect=AssertionError('Model should not be constructed')) as ollama:
            s,out=self.run_case('D',policy=dict(provider='ollama'),ablations=dict(fallback_policy=True))
        ollama.assert_not_called();self.assertEqual(s['provider'],'deterministic')
        self.assertTrue(s['mission_complete']);self.assertFalse(s['llm_inference'])
        self.assertTrue(all(n==0 for n in s['llm_productive_decisions_by_agent'].values()))

    def test_failure_time_is_a_shared_scenario_not_a_failure_oracle(self):
        scenario=ExperimentSchedule('Drone1',8)
        self.assertEqual(scenario.advance(7.9),[]);self.assertEqual(scenario.advance(8),['Drone1'])
        self.assertEqual(scenario.advance(9),[])
        s,out=self.run_case('B',scenario=dict(fail_agent='Drone1',fail_at_s=1))
        self.assertNotIn('SEARCH_SECTOR_A',s['completed_task_ids'])
        self.assertEqual(s['completions_by_agent']['Drone1'],0)
        self.assertFalse(any(e['event'] in ('task_announced','claim_sent') for e in json.loads((out/'protocol_events.json').read_text())))

    def test_model_identity_failure_precedes_vehicle_control(self):
        class Bad(ReplayProvider):
            def verify(self):raise ModelIdentityError('model_digest_mismatch')
        with patch('agentic_uav.experiments.comparison.MockFlight') as backend:
            with self.assertRaises(ModelIdentityError):
                run_comparison(dict(architecture='D',output_dir=str(Path(self.tmp.name)/'bad')),provider=Bad())
        backend.assert_not_called()

    def test_configuration_rejects_mislabelled_ablations_and_optional_unimplemented_e(self):
        for value in [dict(architecture='E'),dict(architecture='C',ablations=dict(task_leases=False)),dict(architecture='D',ablations=dict(unknown=True)),dict(unknown='ignored'),dict(ticks=True),dict(backend='airsim')]:
            with self.assertRaises(ValueError):configuration(value)

    def test_all_architectures_reject_motion_into_the_same_restricted_zone(self):
        mission=copy.deepcopy(self.m)
        mission['guardian']['keepouts']=[dict(x_min=3,x_max=9,y_min=-1,y_max=1,z_min=-4,z_max=-2)]
        path=Path(self.tmp.name)/'blocked.json';path.write_text(json.dumps(mission))
        for architecture in 'ABCD':
            s,out=self.run_case(architecture,mission_config=str(path),ticks=100)
            self.assertFalse(s['mission_complete'])
            self.assertTrue(s['all_dispatched_actions_guarded'])
            self.assertFalse(any(e['kind']=='MOVE' and e['target'][1]==0 for e in json.loads((out/'executed_actions.json').read_text())))


if __name__=='__main__':unittest.main()
