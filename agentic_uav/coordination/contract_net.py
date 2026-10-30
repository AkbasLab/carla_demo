"""Phase 8 contract-net baseline over agent-local Phase 7 endpoints.

No central task owner, LLM, shared agent ledger, or ground-truth task-state reads.
Progress uses INTENT_UPDATE with intent='task_progress' (Phase 7 has no TASK_PROGRESS).
"""
from dataclasses import dataclass, asdict
from enum import Enum
import copy
import math
from agentic_uav.comm.protocol import MessageType as MT, new_message


class TaskType(str, Enum):
    SEARCH_SECTOR = 'SEARCH_SECTOR'
    MAINTAIN_RELAY = 'MAINTAIN_RELAY'
    INSPECT_TARGET = 'INSPECT_TARGET'
    RETURN_TO_BASE = 'RETURN_TO_BASE'


class TaskStatus(str, Enum):
    UNASSIGNED = 'unassigned'
    BIDDING = 'bidding'
    ASSIGNED = 'assigned'
    COMPLETE = 'complete'


@dataclass
class Geometry:
    center: tuple[float, float, float]
    radius_m: float = 1.

    def __post_init__(self):
        if len(self.center)!=3 or not all(math.isfinite(v) for v in self.center) or not math.isfinite(self.radius_m) or self.radius_m<=0:
            raise ValueError('Invalid task geometry')


@dataclass
class MissionTask:
    task_id: str
    task_type: TaskType
    location_or_region: Geometry
    priority: int
    required_capabilities: set[str]
    deadline: float | None = None
    status: TaskStatus = TaskStatus.UNASSIGNED
    assigned_agent: str | None = None
    lease_expires_at: float | None = None
    version: int = 0
    work_units: float = 2.

    def __post_init__(self):
        self.task_type=TaskType(self.task_type)
        self.status=TaskStatus(self.status)
        if not self.task_id or self.version<0 or self.work_units<=0 or not math.isfinite(self.work_units):
            raise ValueError('Invalid task identity, version, or work')
        if self.deadline is not None and (not math.isfinite(self.deadline) or self.deadline<0):
            raise ValueError('Invalid deadline')

    def to_dict(self):
        value=asdict(self)
        value['required_capabilities']=sorted(self.required_capabilities)
        return value

    @classmethod
    def from_dict(cls, value):
        data=copy.deepcopy(value)
        data['location_or_region']=Geometry(**data['location_or_region'])
        data['required_capabilities']=set(data['required_capabilities'])
        return cls(**data)


def bid_cost(task, position, battery, workload, communication_risk, capabilities, weights, role="searcher"):
    if not math.isfinite(workload) or workload<0 or not 0<=battery<=100 or not 0<=communication_risk<=1:
        raise ValueError('Invalid battery or communication risk')
    if not task.required_capabilities <= capabilities:
        return None  # Ineligible, not a high-but-still-winning bid.
    components=dict(distance=math.dist(position,task.location_or_region.center),
        battery=1-battery/100, workload=float(workload), communication=communication_risk,
        mismatch=float(task.task_type!=TaskType.RETURN_TO_BASE and role!={TaskType.SEARCH_SECTOR:'searcher',TaskType.MAINTAIN_RELAY:'relay',TaskType.INSPECT_TARGET:'inspector'}.get(task.task_type)))
    score=sum(weights[k]*v for k,v in components.items())
    if not math.isfinite(score) or score<0:
        raise ValueError('Invalid bid')
    return dict(score=score, components=components)


def preferred_claim(a,b):
    """Higher version, then lowest valid score, then lexical vehicle ID."""
    def key(c):
        if not math.isfinite(c['score']) or c['score']<0 or not c['owner']:
            raise ValueError('Invalid claim')
        return (-c['version'],c['score'],c['owner'])
    return a if key(a)<=key(b) else b


class AllocationAgent:
    def __init__(self, agent_id, peers, endpoint, tasks, position, *, lease_s=2., bid_window=.3,
                 weights=None, capabilities=None, work_rate=1., inject_conflict=False):
        self.agent_id,self.peers,self.endpoint=agent_id,peers,endpoint
        self.tasks={t.task_id:MissionTask.from_dict(t.to_dict()) for t in tasks}
        self.position=list(position)
        self.capabilities=set(capabilities or {'search','inspect','relay','return'})
        self.weights=weights or dict(distance=1.,battery=5.,workload=20.,communication=5.,mismatch=100.)
        if set(self.weights)!= {'distance','battery','workload','communication','mismatch'} or any(not math.isfinite(w) or w<0 for w in self.weights.values()):
            raise ValueError('Invalid weights')
        self.lease_s,self.bid_window,self.work_rate=lease_s,bid_window,work_rate
        self.battery=100.;self.communication_risk=0.
        self.role="searcher"
        self.sequence=0;self.events=[];self.decisions=[]
        self.bids={};self.auction_end={};self.claims={};self.claim_time={};self.acks={}
        self.progress={};self.last_progress={};self.last_heartbeat={}
        self.checkpoints={}
        self.inject_conflict=inject_conflict;self.conflict_injected=False

    def log(self,name,now,**data):
        self.events.append(dict(data,event=name,time_s=now,agent_id=self.agent_id))

    def send(self,kind,payload,now):
        self.sequence+=1
        message=new_message(kind,self.agent_id,self.peers,'phase8',now,self.sequence,payload,ttl=max(5,self.lease_s*2))
        message.message_id=f'phase8:{self.agent_id}:{self.sequence}'
        self.endpoint.send(message)

    def workload(self):
        return sum(t.status==TaskStatus.ASSIGNED and t.assigned_agent==self.agent_id for t in self.tasks.values())

    def announce(self,task,now,version):
        task.version=version;task.status=TaskStatus.BIDDING
        task.assigned_agent=None;task.lease_expires_at=None
        self.bids[task.task_id]={};self.claims.pop(task.task_id,None)
        self.auction_end[task.task_id]=now+self.bid_window
        self.send(MT.TASK_ANNOUNCEMENT,dict(task_id=task.task_id,version=version,
                  bidding_until=now+self.bid_window,resume_index=self.checkpoints.get(task.task_id,0)),now)
        self.offer(task,now)
        self.log('task_announced',now,task_id=task.task_id,version=version)

    def offer(self,task,now):
        if self.workload() or (task.deadline is not None and now>=task.deadline):return
        offer=bid_cost(task,self.position,self.battery,self.workload(),self.communication_risk,self.capabilities,self.weights,self.role)
        if offer is None:return
        payload=dict(task_id=task.task_id,version=task.version,agent_id=self.agent_id,**offer)
        self.bids.setdefault(task.task_id,{})[self.agent_id]=payload
        self.send(MT.TASK_BID,payload,now)
        self.log('bid_computed',now,**payload)

    def adopt(self,task,claim,now):
        if task.status==TaskStatus.COMPLETE or claim['version']!=task.version:return False
        current=self.claims.get(task.task_id)
        winner=claim if current is None else preferred_claim(current,claim)
        if current is not None and winner['owner']!=current['owner']:
            self.log('claim_corrected',now,task_id=task.task_id,previous=current['owner'],winner=winner['owner'],version=task.version)
            if current['owner']==self.agent_id:
                self.send(MT.TASK_RELEASE,dict(task_id=task.task_id,version=task.version,owner=self.agent_id,reason='lost_conflict'),now)
                self.log('losing_claim_released',now,task_id=task.task_id)
        if current is None or winner!=current:
            self.claims[task.task_id]=copy.deepcopy(winner)
            self.claim_time[task.task_id]=now
            self.acks[task.task_id]={self.agent_id}
            task.status=TaskStatus.ASSIGNED;task.assigned_agent=winner['owner']
            task.lease_expires_at=now+self.lease_s
        self.send(MT.TASK_ACCEPT,dict(task_id=task.task_id,version=task.version,owner=winner['owner']),now)
        return True

    def release_task(self,task_id,now):
        task=self.tasks[task_id]
        if task.status!=TaskStatus.ASSIGNED or task.assigned_agent!=self.agent_id:
            raise ValueError('Cannot release a task not owned locally')
        self.send(MT.TASK_RELEASE,dict(task_id=task_id,version=task.version,owner=self.agent_id,reason='voluntary'),now)
        self.log('task_released',now,task_id=task_id,version=task.version)
        self.announce(task,now,task.version+1)

    def receive(self,now):
        for msg in self.endpoint.receive_available():
            if msg.mission_id!='phase8':continue
            p=msg.payload
            if msg.message_type==MT.HEARTBEAT:
                self.last_heartbeat[msg.sender_id]=msg.timestamp
                continue
            task=self.tasks.get(p.get('task_id'))
            if task is None or task.status==TaskStatus.COMPLETE:continue
            version=p.get('version',-1)
            used=False
            if msg.message_type==MT.TASK_ANNOUNCEMENT and version>task.version:
                self.announce(task,now,version);used=True
            elif version==task.version:
                if msg.message_type==MT.TASK_BID and task.status==TaskStatus.BIDDING and msg.sender_id==p.get('agent_id') and math.isfinite(p.get('score',float('nan'))) and p['score']>=0:
                    self.bids.setdefault(task.task_id,{})[msg.sender_id]=p;used=True
                elif msg.message_type==MT.TASK_AWARD and p.get('owner')==msg.sender_id:
                    known=self.bids.get(task.task_id,{}).get(msg.sender_id)
                    if known is not None and known['score']==p.get('score'):
                        used=self.adopt(task,p,now)
                elif msg.message_type==MT.TASK_ACCEPT and p.get('owner')==task.assigned_agent:
                    self.acks.setdefault(task.task_id,set()).add(msg.sender_id);used=True
                elif msg.message_type==MT.INTENT_UPDATE and p.get('intent')=='task_progress' and msg.sender_id==task.assigned_agent and task.lease_expires_at is not None and now<task.lease_expires_at:
                    checkpoint=p.get('completed_waypoints')
                    if checkpoint is not None:
                        if isinstance(checkpoint,bool) or not isinstance(checkpoint,int) or not 0<=checkpoint<=task.work_units:continue
                        self.checkpoints[task.task_id]=max(self.checkpoints.get(task.task_id,0),checkpoint)
                    task.lease_expires_at=now+self.lease_s;used=True
                    self.log('lease_renewed',now,task_id=task.task_id,owner=msg.sender_id)
                elif msg.message_type==MT.TASK_COMPLETE and msg.sender_id==task.assigned_agent and task.lease_expires_at is not None and now<task.lease_expires_at:
                    task.status=TaskStatus.COMPLETE;task.lease_expires_at=None;used=True
                    self.log('completion_received',now,task_id=task.task_id,owner=msg.sender_id)
                elif msg.message_type==MT.TASK_RELEASE and p.get('reason')!='lost_conflict' and msg.sender_id==task.assigned_agent:
                    self.announce(task,now,task.version+1);used=True
            if used:self.decisions.append(msg.message_id)

    def step(self,now,dt,process_inbox=True,execute_mock=True):
        if process_inbox:self.receive(now)
        self.send(MT.HEARTBEAT,dict(alive=True),now)
        for task in self.tasks.values():
            if task.status==TaskStatus.ASSIGNED and now>=task.lease_expires_at:
                self.log('lease_expired',now,task_id=task.task_id,owner=task.assigned_agent,version=task.version,
                         lease_deadline=task.lease_expires_at,completed_waypoints=self.checkpoints.get(task.task_id,0))
                self.announce(task,now,task.version+1)
        # One distributed auction at a time makes workload changes visible before the next task.
        if not any(t.status==TaskStatus.BIDDING for t in self.tasks.values()):
            opened=sorted((t for t in self.tasks.values() if t.status==TaskStatus.UNASSIGNED),key=lambda t:(-t.priority,t.task_id))
            if opened:self.announce(opened[0],now,opened[0].version+1)
        for task in self.tasks.values():
            if task.status==TaskStatus.BIDDING and now>=self.auction_end[task.task_id]:
                offers=self.bids.get(task.task_id,{})
                if not offers:
                    # No eligible idle bidder: reopen later instead of assigning an incapable agent.
                    self.auction_end[task.task_id]=now+self.bid_window
                    self.offer(task,now);continue
                offers={agent:b for agent,b in offers.items() if agent==self.agent_id or now-self.last_heartbeat.get(agent,now)<=self.lease_s}
                if not offers:
                    self.auction_end[task.task_id]=now+self.bid_window
                    self.offer(task,now);continue
                winner=min(offers.values(),key=lambda b:(b['score'],b['agent_id']))
                own=offers.get(self.agent_id)
                inject=self.inject_conflict and not self.conflict_injected and own is not None
                if winner['agent_id']==self.agent_id or inject:
                    proposal=own if inject else winner
                    claim=dict(task_id=task.task_id,version=task.version,owner=self.agent_id,score=proposal['score'])
                    self.send(MT.TASK_AWARD,claim,now);self.adopt(task,claim,now)
                    self.conflict_injected|=inject
                    self.log('claim_sent',now,**claim)
        if not execute_mock:return
        for task in self.tasks.values():
            if task.status!=TaskStatus.ASSIGNED or task.assigned_agent!=self.agent_id:continue
            # Only execute after every peer has acknowledged the current winning claim.
            active_peers={peer for peer in self.peers if now-self.last_heartbeat.get(peer,now)<=self.lease_s}
            if not active_peers<=self.acks.get(task.task_id,set()):continue
            if now-self.claim_time[task.task_id]<self.bid_window:continue
            done=self.progress.get((task.task_id,task.version),0.)+dt*self.work_rate
            self.progress[(task.task_id,task.version)]=done
            self.position=list(task.location_or_region.center)  # Mock task execution, not physical travel.
            if done>=task.work_units:
                self.send(MT.TASK_COMPLETE,dict(task_id=task.task_id,version=task.version,owner=self.agent_id),now)
                task.status=TaskStatus.COMPLETE;task.lease_expires_at=None
                self.log('work_completed',now,task_id=task.task_id,version=task.version)
            elif now-self.last_progress.get(task.task_id,-math.inf)>=self.lease_s/3:
                self.send(MT.INTENT_UPDATE,dict(task_id=task.task_id,version=task.version,intent='task_progress',progress=min(1,done/task.work_units)),now)
                task.lease_expires_at=now+self.lease_s;self.last_progress[task.task_id]=now
                self.log('progress_reported',now,task_id=task.task_id,version=task.version,progress=done/task.work_units)

    def executable_task(self,now):
        for task in self.tasks.values():
            if task.status!=TaskStatus.ASSIGNED or task.assigned_agent!=self.agent_id or now>=task.lease_expires_at:
                continue
            active={p for p in self.peers if now-self.last_heartbeat.get(p,now)<=self.lease_s}
            if active<=self.acks.get(task.task_id,set()) and now-self.claim_time[task.task_id]>=self.bid_window:
                return task
        return None

    def report_execution(self,task_id,version,now,progress,complete=False,completed_waypoints=None):
        task=self.tasks[task_id]
        if (task.version!=version or task.status!=TaskStatus.ASSIGNED or task.assigned_agent!=self.agent_id
                or now>=task.lease_expires_at):
            return False
        if not math.isfinite(progress) or not 0<=progress<=1:
            raise ValueError('Invalid observed progress')
        if completed_waypoints is not None:
            if isinstance(completed_waypoints,bool) or not isinstance(completed_waypoints,int) or not 0<=completed_waypoints<=task.work_units:
                raise ValueError('Invalid waypoint checkpoint')
            self.checkpoints[task_id]=max(self.checkpoints.get(task_id,0),completed_waypoints)
        if complete:
            self.send(MT.TASK_COMPLETE,dict(task_id=task_id,version=version,owner=self.agent_id),now)
            task.status=TaskStatus.COMPLETE;task.lease_expires_at=None
            self.log('work_completed',now,task_id=task_id,version=version,source='observed_waypoint_arrivals')
        else:
            self.send(MT.INTENT_UPDATE,dict(task_id=task_id,version=version,intent='task_progress',progress=progress,completed_waypoints=completed_waypoints),now)
            task.lease_expires_at=now+self.lease_s
            self.log('progress_reported',now,task_id=task_id,version=version,progress=progress,source='observed_motion')
        return True
