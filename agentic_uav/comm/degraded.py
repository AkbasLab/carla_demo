"""Seeded application-network simulator. Infrastructure only, never an agent API."""
from dataclasses import dataclass, asdict, field
import hashlib
import random
import math
from .protocol import PerfectMessageBus, AgentEndpoint, AgentMessage, MessageType


@dataclass
class NetworkConfig:
    latency_ms_mean: float = 10
    latency_ms_jitter: float = 2  # uniform half-width; mean must be >= jitter
    packet_loss_probability: float = 0
    message_rate_limit: float | None = None  # per-sender recipient packets/s
    bandwidth_bytes_per_second: float | None = None  # per-sender shared egress
    communication_range_m: float | None = None
    partitions: list = field(default_factory=list)  # start_s,end_s,groups

    def __post_init__(self):
        for k in ('latency_ms_mean','latency_ms_jitter','packet_loss_probability'):
            v=getattr(self,k)
            if isinstance(v,bool) or not math.isfinite(v) or v<0:raise ValueError(k)
        if self.latency_ms_jitter>self.latency_ms_mean:raise ValueError('jitter exceeds mean')
        if self.packet_loss_probability>1:raise ValueError('Invalid loss probability')
        for k in ('message_rate_limit','bandwidth_bytes_per_second','communication_range_m'):
            v=getattr(self,k)
            if v is not None and (not math.isfinite(v) or v<=0):raise ValueError(k)
        for p in self.partitions:
            if not 0<=p['start_s']<p['end_s'] or not math.isfinite(p['end_s']):raise ValueError('Invalid partition interval')
            members=[a for g in p['groups'] for a in g]
            if len(members)!=len(set(members)):raise ValueError('Partition groups overlap')


def preset(name):
    return NetworkConfig(**{
        'nominal':{},
        'moderate':dict(latency_ms_mean=100,latency_ms_jitter=50,packet_loss_probability=.1),
        'severe':dict(latency_ms_mean=400,latency_ms_jitter=200,packet_loss_probability=.3,message_rate_limit=60,bandwidth_bytes_per_second=50000),
        'partitioned':dict(partitions=[dict(start_s=5,end_s=12,groups=[['Drone1','Drone2'],['Drone3','Drone4']])]),
    }[name])


class DegradedMessageBus(PerfectMessageBus):
    def __init__(self,agent_ids,clock,config,seed=42,positions=None):
        super().__init__(agent_ids,clock)
        self.config=config;self.seed=seed;self.positions=positions
        self._egress={}
        if config.communication_range_m is not None and positions is None:raise ValueError('Range requires infrastructure positions')
        for p in config.partitions:
            if any(a not in self._queues for g in p['groups'] for a in g):raise ValueError('Unknown partition member')

    def _random(self,message,recipient):
        # Independent keyed draws: scheduling changes on other links do not shift draws.
        key=f'{self.seed}|{message.mission_id}|{message.sender_id}|{message.sequence_number}|{recipient}'
        return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest(),'big'))

    def _blocked(self,sender,recipient,t):
        for p in self.config.partitions:
            if p['start_s']<=t<p['end_s']:
                groups={a:i for i,g in enumerate(p['groups']) for a in g}
                if sender in groups and recipient in groups and groups[sender]!=groups[recipient]:return 'partition'
        if self.config.communication_range_m is not None:
            if math.dist(self.positions(sender),self.positions(recipient))>self.config.communication_range_m:return 'out_of_range'
        return None

    def _send(self,agent_id,message):
        start=len(self._log)
        result=super()._send(agent_id,message)
        for r in self._log[start:]:
            rng=self._random(message,r['recipient_id'])
            draw=rng.random();latency=rng.uniform(self.config.latency_ms_mean-self.config.latency_ms_jitter,self.config.latency_ms_mean+self.config.latency_ms_jitter)/1000
            begin=max(r['sent_time'],self._egress.get(agent_id,0))
            service=max(1/self.config.message_rate_limit if self.config.message_rate_limit else 0,
                        r['size_bytes']/self.config.bandwidth_bytes_per_second if self.config.bandwidth_bytes_per_second else 0)
            self._egress[agent_id]=begin+service
            scheduled=begin+service+latency
            reason=self._blocked(agent_id,r['recipient_id'],begin)
            if reason is None and draw<self.config.packet_loss_probability:reason='independent_loss'
            r.update(scheduled_delivery_time=scheduled,transmission_time=begin,latency_sample_s=latency,
                     queue_delay_s=begin-r['sent_time'],loss_draw=draw,drop_reason=reason)
            if reason:r.update(status='dropped',dropped=True)
        return result

    def _receive(self,agent_id):
        now=self._clock();pending=[];delivered=[]
        for serialized,r in sorted(self._queues[agent_id],key=lambda item:item[1]['scheduled_delivery_time']):
            if r['dropped']:continue
            if now>=r['expires_at']:
                r.update(status='expired',dropped=True,expired=True,drop_reason='ttl');continue
            if now<r['scheduled_delivery_time']:
                pending.append((serialized,r));continue
            reason=self._blocked(r['sender_id'],agent_id,r['scheduled_delivery_time'])
            if reason:r.update(status='dropped',dropped=True,drop_reason=reason);continue
            r.update(status='delivered',actual_delivery_time=now)
            self._delivered[(agent_id,r['message_id'])]=r
            delivered.append(AgentMessage.from_json(serialized))
        self._queues[agent_id]=pending
        return delivered


class ObservedEndpoint:
    """Local delivery observations and piggyback acknowledgments; no network config."""
    def __init__(self,endpoint,agent_id,clock,mission_lifetime_s=86400):
        self.endpoint=endpoint;self.agent_id=agent_id;self.clock=clock;self.mission_lifetime_s=mission_lifetime_s
        self.receipts={};self.peers={};self.sent={};self.acked=set()

    def send(self,message):
        m=AgentMessage.from_json(message.to_json())
        m.time_to_live_s={MessageType.HEARTBEAT:1.5,MessageType.INTENT_UPDATE:2.,MessageType.TARGET_FOUND:60.,MessageType.MISSION_UPDATE:self.mission_lifetime_s}.get(m.message_type,m.time_to_live_s)
        m.payload['_delivery_acks']={p:dict(sequence_number=s,timestamp=t) for p,(s,t) in self.receipts.items()}
        self.sent[m.sequence_number]=self.clock()
        # Bound local history; acknowledgments outside this window are ignored.
        self.sent={s:t for s,t in self.sent.items() if self.clock()-t<=60}
        return self.endpoint.send(m)

    def receive_available(self):
        messages=self.endpoint.receive_available();now=self.clock()
        for m in messages:
            p=self.peers.setdefault(m.sender_id,dict(heartbeats=[],highest_sequence=0,missing_sequences=[],rtt_samples_s=[],recent_ack_times=[]))
            high=p['highest_sequence']
            if m.sequence_number>high:
                p['missing_sequences'].extend(range(high+1,m.sequence_number));p['highest_sequence']=m.sequence_number
            elif m.sequence_number in p['missing_sequences']:p['missing_sequences'].remove(m.sequence_number)
            if m.message_type==MessageType.HEARTBEAT:p['heartbeats'].append(now)
            if m.sequence_number>self.receipts.get(m.sender_id,(0,0))[0]:self.receipts[m.sender_id]=(m.sequence_number,m.timestamp)
            ack=m.payload.pop('_delivery_acks',{}).get(self.agent_id)
            if ack:
                s=ack['sequence_number'];key=(m.sender_id,s)
                if s in self.sent and key not in self.acked:
                    p['rtt_samples_s'].append(now-self.sent[s]);p['recent_ack_times'].append(now);self.acked.add(key)
        return messages

    def estimates(self,window_s=5):
        now=self.clock();out={}
        for peer,p in self.peers.items():
            out[peer]=dict(heartbeat_arrival_rate_hz=sum(t>=max(0,now-window_s) for t in p['heartbeats'])/min(window_s,max(now,.1)),
                heartbeat_age_s=now-p['heartbeats'][-1] if p['heartbeats'] else None,
                missing_sequence_count=len(p['missing_sequences']),highest_sequence=p['highest_sequence'],
                acknowledgment_rtt_s=p['rtt_samples_s'][-1] if p['rtt_samples_s'] else None,
                recent_acknowledgments=sum(t>=now-window_s for t in p['recent_ack_times']))
        return out
