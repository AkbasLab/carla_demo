import copy
from contextlib import redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_phase12_agents import run,parse_args,load_mission
from agentic_uav.policy.structured import (ReplayProvider,OllamaProvider,AsyncWorker,PolicyError,
    ModelIdentityError,validate_decision,decision_schema,TOOLS)
from agentic_uav.policy.persistent import PersistentAgent
from agentic_uav.comm.protocol import PerfectMessageBus,MessageType
from agentic_uav.control.runtime_guardian import RuntimeGuardian,GuardedExecutor,Action,State,Outcome


def decision(tool='hold',parameters=None,outgoing=None):
    return dict(situation_assessment=dict(mission_progress='partial',communication_status='nominal',current_risk='low'),
        selected_tool=tool,parameters=parameters if parameters is not None else {'duration_s':1},outgoing_messages=outgoing or [],confidence=.9)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.clock=[0.];self.m,self.cfg,self.tasks,self.routes=load_mission('configs/phase12/mission.example.json')
        self.bus=PerfectMessageBus(list(self.m['vehicles']),lambda:self.clock[0]);self.guardian=RuntimeGuardian(self.cfg)
        self.executed=[];self.gate=GuardedExecutor(self.guardian,lambda a:self.executed.append(a) or dict(executed=True,completed=True),lambda a:True)
        self.agents=[]
        for aid,v in self.m['vehicles'].items():
            a=PersistentAgent(aid,[p for p in self.m['vehicles'] if p!=aid],self.bus.endpoint(aid),self.tasks,v['start_position'],
                role=v['role'],routes=self.routes,home=v['home'],relay_point=self.m['relay_point'],guardian=self.guardian,
                output_dir=self.tmp.name,provider=ReplayProvider(),mission=self.m['mission'],lease_s=45,bid_window=2)
            for p in a.peers:a.peer_beliefs[p]=dict(position=self.m['vehicles'][p]['start_position'],velocity=[0,0,0],observed_at=0,role='SCOUT',battery=80)
            self.agents.append(a)
        self.a=self.agents[0]

    def test_separate_identity_beliefs_memory_and_history(self):
        self.a.memory.append(dict(secret='only_drone1'))
        self.a.tasks['SEARCH_SECTOR_A'].priority=50
        b=self.agents[1]
        self.assertNotIn('only_drone1',json.dumps(b.context(0)))
        self.assertEqual(b.tasks['SEARCH_SECTOR_A'].priority,1)
        self.a.request(0);b.request(0)
        self.assertEqual(self.a.pending['token'],'Drone1:1');self.assertEqual(b.pending['token'],'Drone2:1')
        self.assertNotEqual(self.a.out,b.out)
        self.assertEqual(len(self.a.memory),1);self.assertEqual(len(b.memory),0)

    def test_beliefs_update_only_after_delivery(self):
        self.a.peer_beliefs={}
        peer=self.agents[1];peer.send(MessageType.STATUS_UPDATE,dict(position=[0,8,-3],velocity=[0,0,0],battery=80,role='SCOUT'),0)
        self.assertFalse(self.a.peer_beliefs)
        self.a.receive(0)
        self.assertIn('Drone2',self.a.peer_beliefs)
        self.assertNotIn('Drone3',self.a.peer_beliefs)

    def test_schema_blocks_code_unknown_tools_extra_params_and_nan(self):
        invalid=[]
        d=decision();d['selected_tool']='python_exec';invalid.append(d)
        d=decision();d['parameters']['python']='client.landAsync()';invalid.append(d)
        d=decision();d['confidence']=float('nan');invalid.append(d)
        d=decision('go_to_waypoint',dict(task_id='SEARCH_SECTOR_A',task_version=True,waypoint_index=0,speed_mps=1));invalid.append(d)
        for d in invalid:
            with self.assertRaises(PolicyError):validate_decision(json.dumps(d),self.a.peers)
        with self.assertRaises(PolicyError):validate_decision('{"confidence":0,"confidence":1}',self.a.peers)
        self.assertEqual(set(TOOLS),set(decision_schema()['properties']['selected_tool']['enum']))

    def test_observed_two_field_reply_stays_rejected_with_explicit_feedback(self):
        raw='{"selected_tool":"send_bid","parameters":{"task_id":"SEARCH_SECTOR_A","task_version":1}}'
        with self.assertRaises(PolicyError) as caught:validate_decision(raw,self.a.peers)
        self.assertEqual(str(caught.exception),'decision_fields')
        self.assertEqual(caught.exception.details['missing_fields'],['confidence','outgoing_messages','situation_assessment'])
        self.assertEqual(caught.exception.details['unexpected_fields'],[])

    def test_schema_branches_are_complete_without_parent_merging(self):
        schema=decision_schema();required=set(decision())
        self.assertEqual(len(schema['oneOf']),len(TOOLS))
        for branch in schema['oneOf']:
            self.assertEqual(branch['type'],'object')
            self.assertFalse(branch['additionalProperties'])
            self.assertEqual(set(branch['required']),required)
            self.assertEqual(set(branch['properties']),required)
            tool=branch['properties']['selected_tool']['const']
            params=branch['properties']['parameters']
            self.assertEqual(set(params['required']),set(TOOLS[tool]))
            self.assertFalse(params['additionalProperties'])
            self.assertNotIn('oneOf',branch)
        # Branches must not share mutable common properties.
        schema['oneOf'][0]['properties']['confidence']['minimum']=.5
        self.assertEqual(schema['oneOf'][1]['properties']['confidence']['minimum'],0)

    def test_correction_requests_all_fields_and_requires_model_to_supply_them(self):
        class Correcting(ReplayProvider):
            def generate(self,prompt):
                context=json.loads(prompt)
                if context['correction']:
                    assert set(context['correction']['required_fields'])==set(decision())
                    assert context['correction']['validation_details']['missing_fields']==['confidence','outgoing_messages','situation_assessment']
                    return json.dumps(decision())
                return '{"selected_tool":"hold","parameters":{"duration_s":1}}'
        self.a.provider=Correcting()
        self.a.request(0);self.a.poll(0,self.gate)
        self.assertEqual(self.a.model_decisions,0);self.assertFalse(self.executed)
        self.a.request(0);self.a.poll(0,self.gate)
        self.assertEqual(self.a.model_decisions,1);self.assertEqual(self.a.fallback_count,0)
        self.assertEqual(len(self.executed),1)
        self.assertEqual(self.a.events_policy[0]['validation_details']['missing_fields'],['confidence','outgoing_messages','situation_assessment'])

    def test_outgoing_message_cannot_forge_award_or_unknown_recipient(self):
        d=decision('request_help',dict(reason_code='BASE_LINK_LOST'),[dict(message_type='TASK_AWARD',recipients=['Drone2'],payload={})])
        with self.assertRaises(PolicyError):validate_decision(json.dumps(d),self.a.peers)
        d['outgoing_messages']=[dict(message_type='HELP_REQUEST',recipients=['Drone9'],payload=dict(reason_code='BASE_LINK_LOST'))]
        with self.assertRaises(PolicyError):validate_decision(json.dumps(d),self.a.peers)

    def test_targeted_help_uses_only_selected_inbox(self):
        d=decision('request_help',dict(reason_code='BASE_LINK_LOST'),[dict(message_type='HELP_REQUEST',recipients=['Drone2'],payload=dict(reason_code='BASE_LINK_LOST'))])
        d=validate_decision(json.dumps(d),self.a.peers)
        self.a.apply(d,0,self.gate)
        self.assertEqual(len(self.bus.endpoint('Drone2').receive_available()),1)
        self.assertEqual(self.bus.endpoint('Drone3').receive_available(),[])

    def test_deterministic_calculations_and_no_fabricated_ownership(self):
        result=self.a.apply(decision('compute_task_cost',dict(task_id='SEARCH_SECTOR_A')),0,self.gate)
        self.assertEqual(result['distance_m'],8);self.assertEqual(result['travel_time_s'],8)
        self.assertEqual(result['distance_to_entry_m'],4)
        self.assertTrue(result['battery_sufficient']);self.assertTrue(result['route_feasible'])
        with self.assertRaises(PolicyError):self.a.apply(decision('start_search',dict(task_id='SEARCH_SECTOR_A',task_version=0)),0,self.gate)
        with self.assertRaises(PolicyError):self.a.apply(decision('report_target',dict(observation_id='invented')),0,self.gate)
        self.assertFalse(self.executed)

    def test_one_correction_then_deterministic_fallback(self):
        class Bad(ReplayProvider):
            def generate(self,prompt):return '{bad json'
        self.a.provider=Bad()
        self.a.request(0);self.a.poll(0,self.gate)
        self.assertEqual(self.a.correction_attempt,1);self.assertEqual(self.a.fallback_count,0)
        self.a.request(0);self.a.poll(0,self.gate)
        self.assertEqual(self.a.fallback_count,1)
        self.assertEqual(sum(e['event']=='structured_correction_requested' for e in self.a.events_policy),1)
        self.assertEqual(len(self.executed),1)
        self.assertEqual(self.executed[0].kind,'HOLD')

    def test_nonblocking_timeout_heartbeat_and_late_response(self):
        ready=threading.Event()
        class Slow:
            def generate(self,prompt):ready.wait(1);return json.dumps(decision())
        self.a.worker=AsyncWorker(Slow());self.a.inference_timeout=.01
        self.a.request(0);self.a.pending['wall_start']-=1
        self.a.protocol_tick(0,.2)  # Must progress while inference is blocked.
        self.assertTrue(any(m['message_type']=='HEARTBEAT' for m in self.bus.logs()))
        self.a.poll(0,self.gate);self.assertEqual(self.a.fallback_count,1);self.assertIsNone(self.a.pending)
        ready.set();self.a.worker.thread.join(.5);self.a.poll(0,self.gate)
        self.assertTrue(any(e['event']=='late_response_discarded' for e in self.a.events_policy))
        self.assertEqual(self.a.model_decisions,0)

    def test_late_result_is_timed_out_even_if_already_queued(self):
        self.a.request(0)
        self.a.pending['inline_result']['latency_s']=16
        self.a.poll(0,self.gate)
        self.assertEqual(self.a.fallback_count,1);self.assertEqual(self.a.model_decisions,0)

    def test_stale_context_and_task_epoch_cannot_restart_motion(self):
        self.a.request(0);self.a.max_context_age=1
        self.a.poll(2,self.gate)
        self.assertEqual(self.a.model_decisions,0)
        task=self.a.tasks['SEARCH_SECTOR_A'];task.version=5
        with self.assertRaises(PolicyError):self.a.apply(decision('accept_task',dict(task_id=task.task_id,task_version=4)),0,self.gate)

    def test_role_changes_follow_deterministic_constraints(self):
        with self.assertRaises(PolicyError):self.a.apply(decision('change_role',dict(new_role='RESERVE',reason_code='NO_TASK')),0,self.gate)
        b=self.agents[1]
        with self.assertRaises(PolicyError):b.apply(decision('change_role',dict(new_role='RELAY',reason_code='ROLE_NEEDED')),0,self.gate)
        result=self.a.apply(decision('change_role',dict(new_role='RELAY',reason_code='ROLE_NEEDED')),0,self.gate)
        self.assertEqual(result['role'],'RELAY')

    def test_unsafe_motion_never_bypasses_guardian(self):
        self.a.role='RELAY';self.a.relay_point=(100,0,-3)
        with self.assertRaises(PolicyError):self.a.apply(decision('act_as_relay',{}),0,self.gate)
        self.assertFalse(self.executed)
        self.assertIn('geofence',self.gate.audit[-1]['reasons'])

    def test_known_target_report_and_versioned_release(self):
        self.a.observations['T1']=dict(position=[5,0,-3],observed_at=0)
        result=self.a.apply(decision('report_target',dict(observation_id='T1')),0,self.gate)
        self.assertEqual(result['status'],'target_reported')
        self.agents[1].receive(0)
        self.assertIn('INSPECT_T1',self.agents[1].tasks)
        self.assertEqual(self.agents[1].routes['INSPECT_T1'],[[5,0,-3]])
        self.assertIsNone(self.agents[1].tasks['INSPECT_T1'].assigned_agent)

    def test_model_identity_fault_disables_future_requests(self):
        self.a.request(0);self.a.pending['inline_result']=dict(token='Drone1:1',error_type='ModelIdentityError',latency_s=0)
        self.a.poll(0,self.gate)
        self.assertTrue(self.a.identity_fault)
        count=self.a.request_number;self.a.request(10)
        self.assertEqual(self.a.request_number,count)

    def test_replay_end_to_end_four_contexts_and_guarded_flight(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            summary=run(parse_args(['--output-dir',tmp+'/run']))
            self.assertTrue(summary['mission_complete']);self.assertFalse(summary['llm_inference'])
            self.assertFalse(summary['llm_exit_criterion_observed']);self.assertFalse(summary['live_exit_criterion_observed'])
            self.assertTrue(summary['all_dispatched_actions_guarded'])
            self.assertEqual(summary['duplicate_task_completions'],0)
            self.assertTrue(all(n>0 for n in summary['decisions_by_agent'].values()))
            root=Path(tmp)/'run'
            actual=json.loads((root/'executed_actions.json').read_text())
            audit=json.loads((root/'guardian_audit.json').read_text())
            approved={e['selected_action']['command_id'] for e in audit if e['selected_action'] and e['mission_effect']['executed']}
            self.assertTrue(all(e['command_id'] in approved for e in actual))
            arrivals=json.loads((root/'waypoint_arrivals.json').read_text())
            self.assertEqual(len(arrivals),8)
            for aid in self.m['vehicles']:
                prompts=[json.loads(line) for line in (root/aid/'prompts.jsonl').read_text().splitlines()]
                self.assertTrue(prompts)
                self.assertTrue(all(json.loads(p['prompt'])['agent_id']==aid for p in prompts))


class AirSimInterfaceTests(unittest.TestCase):
    def test_explicit_frame_conversion_and_cancel_ack(self):
        from types import SimpleNamespace
        from agentic_uav.policy.backends import AirSimFlight
        calls=[]
        vector=lambda x,y,z:SimpleNamespace(x_val=x,y_val=y,z_val=z)
        class Client:
            def __init__(self,**kwargs):pass
            def confirmConnection(self):pass
            def listVehicles(self):return ['Drone1','Drone2','Drone3','Drone4']
            def getMultirotorState(self,vehicle_name):
                return SimpleNamespace(kinematics_estimated=SimpleNamespace(position=vector(0,0,28),linear_velocity=vector(0,0,0)),landed_state=0)
            def moveToPositionAsync(self,*target,**kwargs):calls.append(('move',target,kwargs))
            def cancelLastTask(self,**kwargs):calls.append(('cancel',kwargs))
            def hoverAsync(self,**kwargs):calls.append(('hover',kwargs))
        fake=SimpleNamespace(MultirotorClient=Client,LandedState=SimpleNamespace(Landed=0))
        m=json.loads(Path('configs/phase12/carlaair.example.json').read_text())
        with patch.dict(sys.modules,{'airsim':fake}):
            backend=AirSimFlight(m['vehicles'],lambda:0,ground_z=28)
            self.assertEqual(backend.sample('Drone2')['position'],[0,5,28])
            backend.execute(Action('move','Drone2','MOVE',0,30,((4,5,25),),1))
            self.assertEqual(calls[0][1],(4,0,25))
            self.assertTrue(backend.cancel('Drone2'))
            self.assertEqual(calls[-1][0],'hover')


class ModelPinTests(unittest.TestCase):
    def test_latest_or_unpinned_model_rejected(self):
        for name,digest in [('llama3.1:latest','a'*64),('llama3.1','a'*64),('llama3.1:8b',None)]:
            with self.assertRaises(ModelIdentityError):OllamaProvider(name,digest)

    def test_pin_checked_before_and_after_inference(self):
        p=OllamaProvider('llama3.1:8b','a'*64)
        tags=dict(models=[dict(name='llama3.1:8b',digest='a'*64)])
        calls=[]
        def http(path,data=None):
            calls.append((path,data))
            if path=='/api/version':return dict(version='test-version')
            if path=='/api/tags':return copy.deepcopy(tags)
            if path=='/api/chat':return dict(message=dict(content=json.dumps(decision())))
            raise AssertionError(path)
        p._http=http
        validate_decision(p.generate('{}'),['Drone2'])
        self.assertEqual(sum(path=='/api/tags' for path,data in calls),2)
        chat=next(data for path,data in calls if path=='/api/chat')
        self.assertEqual(chat['options']['temperature'],0)
        self.assertEqual(chat['format'],decision_schema())
        system=chat['messages'][0]['content']
        for field in decision():self.assertIn(field,system)
        self.assertIn('Never return only selected_tool and parameters',system)
        tags['models'][0]['digest']='b'*64
        with self.assertRaises(ModelIdentityError):p.generate('{}')

    def test_mutation_during_generation_rejected(self):
        p=OllamaProvider('llama3.1:8b','a'*64);count=[0]
        def http(path,data=None):
            if path=='/api/version':return dict(version='test-version')
            if path=='/api/tags':
                count[0]+=1;return dict(models=[dict(name='llama3.1:8b',digest=('a' if count[0]==1 else 'b')*64)])
            return dict(message=dict(content=json.dumps(decision())))
        p._http=http
        with self.assertRaises(ModelIdentityError):p.generate('{}')

    def test_in_progress_takeoff_keeps_guardian_phase_checks(self):
        _,cfg,_,_=load_mission('configs/phase12/mission.example.json')
        guardian=RuntimeGuardian(cfg)
        state=State('Drone1',(0,0,-1),0,80,(0,0,-3),flight_phase='TAKEOFF')
        action=Action('takeoff','Drone1','TAKEOFF',0,10,((0,0,-3),),1)
        self.assertEqual(guardian.evaluate(action,state,0).outcome,Outcome.APPROVE)
        self.assertIsNone(guardian.evaluate(action,replace(state,flight_phase='AIRBORNE'),0).selected_action)
