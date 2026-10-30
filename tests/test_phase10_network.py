import unittest
import json
import tempfile
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from agentic_uav.comm.degraded import NetworkConfig,DegradedMessageBus,ObservedEndpoint,preset
from agentic_uav.comm.protocol import AgentMessage,MessageType
from run_phase9_roles import run
from contextlib import redirect_stdout
import io


def message(i,now=0,ttl=10,recipients=None,sender='a'):
    return AgentMessage(f'{sender}:{i}',MessageType.HEARTBEAT,sender,recipients or ['b'],'test',now,i,ttl,{'alive':True})


class NetworkTests(unittest.TestCase):
    def sample(self,seed=42):
        clock=[0.];bus=DegradedMessageBus(['a','b'],lambda:clock[0],NetworkConfig(latency_ms_mean=100,latency_ms_jitter=40,packet_loss_probability=.3),seed)
        for i in range(1,10001):bus.endpoint('a').send(message(i))
        clock[0]=1;bus.endpoint('b').receive_available()
        return bus.logs()

    def test_statistical_loss_latency_and_reproducibility(self):
        logs=self.sample();self.assertEqual(logs,self.sample())
        self.assertNotEqual(logs,self.sample(43))
        loss=sum(r['drop_reason']=='independent_loss' for r in logs)/len(logs)
        self.assertLess(abs(loss-.3),.02)
        lat=[r['latency_sample_s'] for r in logs]
        self.assertTrue(all(.06<=v<=.14 for v in lat))
        self.assertLess(abs(sum(lat)/len(lat)-.1),.002)
        # Uniform jitter's expected variance is half-width squared / 3.
        self.assertLess(abs(sum((x-.1)**2 for x in lat)/len(lat)-.04**2/3),.00004)

    def test_scheduled_delivery_and_expiration(self):
        clock=[0.];bus=DegradedMessageBus(['a','b'],lambda:clock[0],NetworkConfig(latency_ms_mean=500,latency_ms_jitter=0))
        bus.endpoint('a').send(message(1,ttl=.2));bus.endpoint('a').send(message(2,ttl=2))
        self.assertEqual(bus.endpoint('b').receive_available(),[])
        clock[0]=.5
        self.assertEqual([m.sequence_number for m in bus.endpoint('b').receive_available()],[2])
        self.assertEqual(bus.logs()[0]['status'],'expired')

    def test_partition_only_cross_group_links_and_interval(self):
        clock=[1.];bus=DegradedMessageBus(['a','b','c'],lambda:clock[0],NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0,
            partitions=[dict(start_s=1,end_s=2,groups=[['a','b'],['c']])]))
        bus.endpoint('a').send(message(1,1,recipients=['b','c']))
        self.assertEqual(len(bus.endpoint('b').receive_available()),1)
        self.assertEqual(bus.endpoint('c').receive_available(),[])
        clock[0]=2;bus.endpoint('a').send(message(2,2,recipients=['c']))
        self.assertEqual(len(bus.endpoint('c').receive_available()),1)

    def test_egress_bandwidth_and_rate(self):
        clock=[0.];bus=DegradedMessageBus(['a','b'],lambda:clock[0],NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0,message_rate_limit=2,bandwidth_bytes_per_second=100))
        for i in [1,2]:bus.endpoint('a').send(message(i,ttl=100))
        logs=bus.logs();duration=logs[0]['size_bytes']/100
        self.assertAlmostEqual(logs[0]['scheduled_delivery_time'],duration)
        self.assertAlmostEqual(logs[1]['transmission_time'],duration)
        bus2=DegradedMessageBus(['a','b'],lambda:0,NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0,message_rate_limit=2))
        bus2.endpoint('a').send(message(1));self.assertEqual(bus2.logs()[0]['scheduled_delivery_time'],.5)

    def test_range_and_observed_ack(self):
        clock=[0.];positions={'a':(0,0,0),'b':(10,0,0)}
        bus=DegradedMessageBus(['a','b'],lambda:clock[0],NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0,communication_range_m=5),positions=positions.get)
        bus.endpoint('a').send(message(1));self.assertEqual(bus.logs()[0]['drop_reason'],'out_of_range')
        positions['b']=(1,0,0)
        a=ObservedEndpoint(bus.endpoint('a'),'a',lambda:clock[0]);b=ObservedEndpoint(bus.endpoint('b'),'b',lambda:clock[0])
        a.send(message(2));clock[0]=.1;b.receive_available()
        b.send(message(1,.1,recipients=['a'],sender='b'));clock[0]=.2;a.receive_available()
        self.assertAlmostEqual(a.estimates()['b']['acknowledgment_rtt_s'],.2)
        self.assertNotIn('packet_loss_probability',a.estimates()['b'])

    def test_mission_replay_all_conditions(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(io.StringIO()):
            for condition in ['nominal','moderate','severe','partitioned']:
                results=[]
                for n in range(2):
                    out=Path(tmp)/f'{condition}{n}'
                    summary=run(ticks=400,output_dir=out,fail_agent=None,network_config=preset(condition),seed=42)
                    results.append([(out/f'{name}.json').read_text() for name in ['summary','events','messages','beliefs']])
                self.assertEqual(*results,condition)
                if condition=='nominal':self.assertTrue(summary['mission_complete'])

    def test_jitter_reorders_by_network_arrival(self):
        clock=[0.];bus=DegradedMessageBus(['a','b'],lambda:clock[0],NetworkConfig(latency_ms_mean=100,latency_ms_jitter=100))
        for i in range(1,21):bus.endpoint('a').send(message(i))
        clock[0]=.3
        received=[m.message_id for m in bus.endpoint('b').receive_available()]
        expected=[r['message_id'] for r in sorted(bus.logs(),key=lambda r:r['scheduled_delivery_time'])]
        self.assertEqual(received,expected)
        self.assertNotEqual(received,[f'a:{i}' for i in range(1,21)])

    def test_invalid_configuration(self):
        for kw in [dict(packet_loss_probability=1.1),dict(latency_ms_mean=-1),dict(latency_ms_jitter=100),dict(message_rate_limit=0)]:
            with self.assertRaises(ValueError):NetworkConfig(**kw)

if __name__=='__main__':unittest.main()
