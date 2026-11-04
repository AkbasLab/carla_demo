"""Regression for easy_run2: valid HOLD responses must not imply mission control."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import test_phase12_agents as fixtures
from agentic_uav.policy.evidence import admit_requests,policy_evidence
from agentic_uav.policy.structured import decision_schema,validate_decision,ReplayProvider,PolicyError,OllamaProvider
from agentic_uav.coordination.contract_net import TaskStatus
from run_phase12_agents import run,parse_args


class ProgressTests(unittest.TestCase):
    setUp=fixtures.AgentTests.setUp

    def owned_ready(self,now=3):
        a=self.a;t=a.tasks['SEARCH_SECTOR_A']
        t.status=TaskStatus.ASSIGNED;t.assigned_agent=a.agent_id;t.version=1;t.lease_expires_at=1000
        a.claim_time[t.task_id]=0;a.acks[t.task_id]=set(a.peers)
        self.fresh(now);a._update_opportunity(now)
        return t

    def fresh(self,now):
        self.clock[0]=now;self.a.state_time=now
        self.a.last_heartbeat={p:now for p in self.a.peers}
        for b in self.a.peer_beliefs.values():b['observed_at']=now

    def test_executable_task_has_actionable_start_example_and_no_bid(self):
        t=self.owned_ready()
        context=self.a.context(3)
        self.assertEqual(context['decision_format']['example']['selected_tool'],'start_search')
        self.assertIn('start_search',context['available_tools'])
        self.assertNotIn('send_bid',context['available_tools'])
        self.assertEqual(context['tool_candidates']['start_search'],[dict(task_id=t.task_id,task_version=1)])
        schema=decision_schema(context)
        tools={b['properties']['selected_tool']['const'] for b in schema['oneOf']}
        self.assertNotIn('send_bid',tools)
        branch=next(b for b in schema['oneOf'] if b['properties']['selected_tool']['const']=='start_search')
        self.assertEqual(branch['properties']['parameters']['properties']['task_id']['enum'],[t.task_id])
        self.assertEqual(branch['properties']['parameters']['properties']['task_version']['enum'],[1])
        hold=next(b for b in schema['oneOf'] if b['properties']['selected_tool']['const']=='hold')
        self.assertEqual(hold['properties']['parameters']['properties']['duration_s']['maximum'],2)

    def test_repeated_deferral_is_correctable_only_when_route_is_safe(self):
        self.owned_ready();self.a.progress_timeout=2;self.a.opportunity_deferrals=2;self.fresh(6)
        with self.assertRaises(PolicyError) as e:self.a._check_progress(fixtures.decision(),6,self.gate)
        self.assertEqual(str(e.exception),'mission_progress_stall')
        self.a.peer_beliefs['Drone2']['position']=[4,0,-3]
        self.a._check_progress(fixtures.decision(),6,self.gate)  # Hazard makes hold legitimate.
        self.a.peer_beliefs['Drone2']['position']=[0,8,-3]
        self.a.peer_beliefs['Drone2']['observed_at']=0
        self.a._check_progress(fixtures.decision(),6,self.gate)  # Unknown state must never pressure motion.

    def test_first_delayed_calculation_is_not_treated_as_repeated_deferral(self):
        self.owned_ready();self.a.progress_timeout=2;self.fresh(6)
        self.a._check_progress(fixtures.decision('compute_task_cost',dict(task_id='SEARCH_SECTOR_A')),6,self.gate)
        self.assertEqual(self.a.opportunity_deferrals,0)

    def test_hold_duration_cannot_block_policy_for_thirty_seconds(self):
        with self.assertRaises(PolicyError) as e:self.a.apply(fixtures.decision('hold',dict(duration_s=30)),0,self.gate)
        self.assertEqual(str(e.exception),'hold_duration_exceeds_policy_limit')
        self.assertFalse(self.executed)

    def test_search_authorization_audit_is_atomic_and_attributable(self):
        t=self.owned_ready();self.a.request_number=1
        raw=fixtures.decision('start_search',dict(task_id=t.task_id,task_version=1))
        result=self.a.apply(raw,3,self.gate)
        self.assertEqual(result['status'],'search_authorized')
        self.assertEqual(self.a.authorization['request_id'],'Drone1:1')
        self.assertEqual(self.a.authorization['source'],'replay_fixture')
        self.assertEqual(self.a.events_policy[-1]['event'],'search_authorized')
        json.dumps(self.a.events_policy,allow_nan=False)

    def test_hold_only_policy_can_recover_without_receiving_llm_credit(self):
        class HoldOnly(ReplayProvider):
            def generate(self,prompt):return json.dumps(fixtures.decision())
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            args=parse_args(['--progress-timeout','2','--ticks','400','--output-dir',tmp+'/run'])
            summary=run(args,provider=HoldOnly())
            self.assertTrue(summary['mission_complete'])
            self.assertTrue(any(summary['fallbacks_by_agent'].values()))
            self.assertFalse(summary['llm_exit_criterion_observed'])
            self.assertFalse(summary['cooperative_mission_success'])
            self.assertTrue(all(count==0 for count in summary['productive_decisions_by_agent'].values()))
            self.assertTrue(all(count==0 for count in summary['llm_productive_decisions_by_agent'].values()))
            self.assertTrue(all(sources.get('deterministic_fallback',0)>0 for sources in summary['observed_progress_sources_by_agent'].values()))
            arrivals=json.loads((Path(tmp)/'run'/'waypoint_arrivals.json').read_text())
            self.assertTrue(arrivals)
            self.assertTrue(all(a['authorization_source']=='deterministic_fallback' for a in arrivals))

    def test_progressing_replay_has_observed_policy_effects_and_no_llm_claim(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            summary=run(parse_args(['--output-dir',tmp+'/run']))
            self.assertTrue(summary['mission_complete'])
            self.assertTrue(all(n>0 for n in summary['productive_decisions_by_agent'].values()))
            self.assertTrue(all(n==0 for n in summary['llm_productive_decisions_by_agent'].values()))
            events=[json.loads(line) for path in (Path(tmp)/'run').glob('Drone*/decision_history.jsonl') for line in path.read_text().splitlines()]
            self.assertTrue(any(e['event']=='search_authorized' for e in events))
            self.assertFalse(any(e['event']=='policy_error' and e['reason_code']=='TypeError' for e in events))
            self.assertFalse(summary['llm_exit_criterion_observed'])


class EvidenceTests(unittest.TestCase):
    def agents(self,tool='hold',progress=False,source='llm'):
        agents=[]
        for i in range(4):
            rid=f'Drone{i+1}:1'
            events=[dict(event='policy_decision_applied',request_id=rid,source='llm',flight_phase='AIRBORNE',decision=fixtures.decision(tool,dict(task_id='A',task_version=1) if tool=='start_search' else None))]
            if progress:events.append(dict(event='policy_progress_observed',request_id=rid,source=source))
            agents.append(SimpleNamespace(agent_id=f'Drone{i+1}',events_policy=events))
        return agents

    def test_hold_only_integration_is_not_a_productive_exit(self):
        # Even a wrongly attributed HOLD progress event must not inflate the metric.
        s=policy_evidence(self.agents(progress=True),'ollama',True,None,False,0,'mock')
        self.assertTrue(s['llm_integration_observed'])
        self.assertFalse(s['llm_exit_criterion_observed'])
        self.assertFalse(s['cooperative_mission_success'])

    def test_fallback_progress_cannot_be_credited_to_an_llm(self):
        s=policy_evidence(self.agents('start_search',True,'deterministic_fallback'),'ollama',True,None,True,0,'mock')
        self.assertFalse(s['llm_exit_criterion_observed'])
        self.assertTrue(all(v==0 for v in s['llm_productive_decisions_by_agent'].values()))

    def test_real_accepted_motion_requires_observed_effects_and_guard_coverage(self):
        s=policy_evidence(self.agents('start_search',False),'ollama',True,None,True,0,'mock')
        self.assertFalse(s['llm_exit_criterion_observed'])
        s=policy_evidence(self.agents('start_search',True),'ollama',True,None,True,0,'mock')
        self.assertTrue(s['llm_exit_criterion_observed']);self.assertTrue(s['cooperative_mission_success'])
        self.assertFalse(s['live_exit_criterion_observed'])
        s=policy_evidence(self.agents('start_search',True),'ollama',False,None,True,0,'mock')
        self.assertFalse(s['llm_exit_criterion_observed'])

    def test_inference_admission_is_bounded_and_fair(self):
        issued=[]
        class Waiting:
            def __init__(self,name):
                self.agent_id=name;self.authorized=None;self.identity_fault=False;self.pending=None
                self.worker=None;self.last_request=-float('inf');self.decision_interval=1;self.request_waiting_since=None
            def request(self,now):issued.append(self.agent_id);self.pending={};self.last_request=now
        agents=[Waiting('Drone1'),Waiting('Drone2')]
        self.assertEqual(admit_requests(agents,0,1),['Drone1'])
        self.assertEqual(admit_requests(agents,1,1),[])
        agents[0].pending=None
        self.assertEqual(admit_requests(agents,2,1),['Drone2'])
        self.assertEqual(issued,['Drone1','Drone2'])

    def test_failed_warmup_aborts_before_vehicle_backend(self):
        from unittest.mock import patch
        class BadWarmup(OllamaProvider):
            def __init__(self):pass
            def verify(self):return dict(provider='ollama',model='test:pinned',digest='a'*64)
            def warmup(self):raise TimeoutError('load timeout')
        with tempfile.TemporaryDirectory() as tmp:
            args=parse_args(['--output-dir',tmp+'/run'])
            with patch('run_phase12_agents.MockFlight') as backend:
                with self.assertRaises(TimeoutError):run(args,provider=BadWarmup())
                backend.assert_not_called()
            error=json.loads((Path(tmp)/'run'/'preflight_error.json').read_text())
            self.assertFalse(error['vehicle_control_started'])

    def test_warmup_preserves_pin_and_does_not_generate_agent_decisions(self):
        provider=OllamaProvider('llama3.1:8b','a'*64);calls=[]
        def http(path,data=None):
            calls.append((path,data))
            if path=='/api/version':return dict(version='test')
            if path=='/api/tags':return dict(models=[dict(name='llama3.1:8b',digest='a'*64)])
            if path=='/api/generate':return dict(done=True)
            raise AssertionError(path)
        provider._http=http;result=provider.warmup()
        self.assertTrue(result['performed'])
        self.assertEqual(sum(p=='/api/tags' for p,d in calls),2)
        self.assertFalse(any(p=='/api/chat' for p,d in calls))
        self.assertEqual(next(d for p,d in calls if p=='/api/generate')['prompt'],'')
