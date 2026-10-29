import json
import tempfile
import unittest
from pathlib import Path
from agentic_uav.comm.protocol import AgentMessage, MessageType, PerfectMessageBus, new_message
from agentic_uav.comm.phase7_demo import ProtocolAgent, run_protocol_demo


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.now=0.
        self.bus=PerfectMessageBus(['a','b','c'],lambda:self.now)
        self.a,self.b,self.c=[self.bus.endpoint(k) for k in ('a','b','c')]

    def message(self, kind=MessageType.STATUS_UPDATE, seq=1, recipients=None):
        return new_message(kind,'a',recipients or ['b'],'m',self.now,seq,{'position':[1,2,3]})

    def test_endpoint_has_only_two_public_methods(self):
        self.assertEqual([name for name in dir(self.a) if not name.startswith('_')], ['receive_available', 'send'])

    def test_all_types_round_trip(self):
        self.assertEqual(len(MessageType),13)
        for i,kind in enumerate(MessageType,1):
            m=self.message(kind,i)
            self.assertEqual(AgentMessage.from_json(m.to_json()),m)
            self.a.send(m)
        self.assertEqual(len(self.b.receive_available()),13)

    def test_recipient_isolation_and_snapshot(self):
        m=self.message(recipients=['b','c']);self.a.send(m)
        m.payload['position'][0]=999
        first=self.b.receive_available()[0];first.payload['position'][0]=123
        self.assertEqual(self.c.receive_available()[0].payload['position'][0],1)
        self.assertEqual(self.a.receive_available(),[])
        self.assertEqual(self.b.receive_available(),[])

    def test_beliefs_wait_for_receipt(self):
        agent=ProtocolAgent('b',['a'],self.b)
        m=self.message();m.mission_id='phase7-demo';self.a.send(m)
        self.assertEqual(agent.team_beliefs,{})
        agent.receive()
        self.assertEqual(agent.team_beliefs['a']['position'],[1,2,3])

    def test_expiry_and_log_fields(self):
        m=self.message();self.a.send(m);self.now=5
        self.assertEqual(self.b.receive_available(),[])
        r=self.bus.logs()[0]
        self.assertEqual(r['status'],'expired')
        self.assertIsNone(r['actual_delivery_time'])
        self.assertGreater(r['size_bytes'],0)
        with self.assertRaises(ValueError):self.bus.record_decision('b',m.message_id)

    def test_impersonation_unknown_recipient_and_duplicates(self):
        m=self.message()
        with self.assertRaises(ValueError):self.b.send(m)
        self.a.send(m)
        with self.assertRaises(ValueError):self.a.send(m)
        with self.assertRaises(ValueError):self.a.send(self.message(seq=2,recipients=['unknown']))
        with self.assertRaises(ValueError):self.a.send(self.message(seq=1))

    def test_delivered_decision_logging(self):
        m=self.message();self.a.send(m);self.b.receive_available();self.bus.record_decision('b',m.message_id)
        log=self.bus.logs()[0]
        self.assertEqual(log['status'],'delivered');self.assertTrue(log['influenced_decision'])
        log['status']='changed'
        self.assertEqual(self.bus.logs()[0]['status'],'delivered')

    def test_validation(self):
        m=self.message()
        for key,value in [('time_to_live_s',0),('confidence',2),('timestamp',float('nan')),('sequence_number',True),('recipient_ids',['b','b'])]:
            data=json.loads(m.to_json());data[key]=value
            with self.assertRaises(ValueError):AgentMessage(**data)

    def test_four_agent_exit_demo(self):
        with tempfile.TemporaryDirectory() as d:
            result=run_protocol_demo(3,output_dir=d)
            self.assertEqual(result['agents'],4)
            self.assertTrue(result['all_peer_beliefs_present'])
            self.assertEqual(result['delivered'],result['recipient_deliveries'])
            logs=json.loads((Path(d)/'messages.json').read_text())
            self.assertEqual(set(r['message_type'] for r in logs),set(t.value for t in MessageType))
