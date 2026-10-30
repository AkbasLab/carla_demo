"""Phase 9 deterministic local roles and staged health beliefs; no LLM.

Silence means UNREACHABLE, not FAILED. Confirmed failure requires a configured
supervisor message. Reappearing peers are RECOVERED, not automatically authorized
to resume old task execution.
"""
from enum import Enum
import math
from agentic_uav.comm.protocol import MessageType as MT
from agentic_uav.coordination.contract_net import AllocationAgent,TaskType,TaskStatus


class Role(str,Enum):
    SCOUT='SCOUT'
    RELAY='RELAY'
    RESERVE='RESERVE'


class Health(str,Enum):
    HEALTHY='HEALTHY'
    SUSPECTED='SUSPECTED'
    UNREACHABLE='UNREACHABLE'
    FAILED='FAILED'
    RECOVERED='RECOVERED'


class PeerHealth:
    def __init__(self,suspect_after=1.,unreachable_after=3.,recovery_dwell=1.):
        if not 0<suspect_after<unreachable_after or recovery_dwell<=0:
            raise ValueError('Invalid health thresholds')
        self.suspect_after=suspect_after;self.unreachable_after=unreachable_after;self.recovery_dwell=recovery_dwell
        self.last_seen=0.;self.state=Health.HEALTHY;self.recovered_at=None

    def heartbeat(self,now):
        if self.state in (Health.UNREACHABLE,Health.FAILED):
            self.state=Health.RECOVERED;self.recovered_at=now
        elif self.state==Health.SUSPECTED:self.state=Health.HEALTHY
        self.last_seen=now

    def tick(self,now):
        age=now-self.last_seen
        if self.state==Health.FAILED:return self.state
        if age>=self.unreachable_after:
            self.state=Health.UNREACHABLE;self.recovered_at=None
        elif age>=self.suspect_after and self.state!=Health.RECOVERED:self.state=Health.SUSPECTED
        elif self.state==Health.RECOVERED and now-self.recovered_at>=self.recovery_dwell and age<self.suspect_after:
            self.state=Health.HEALTHY
        return self.state

    def confirmed_failure(self):
        self.state=Health.FAILED


class DynamicRoleAgent(AllocationAgent):
    def __init__(self,*args,initial_roles,relay_point=(5,5,-3),suspect_after=1.,unreachable_after=3.,
                 low_battery=25.,critical_priority=10,supervisor_id=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.role=Role(initial_roles[self.agent_id])
        self.initial_roles={a:Role(r) for a,r in initial_roles.items()}
        self.peer_health={p:PeerHealth(suspect_after,unreachable_after) for p in self.peers}
        self.peer_status={};self.relay_point=list(relay_point);self.low_battery=low_battery
        self.critical_priority=critical_priority;self.supervisor_id=supervisor_id
        self.objective='FULL_MISSION';self.quarantined=False;self._deferred=[]

    def receive(self,now):
        # Phase 7 API only. Parent consumes the allocation envelopes through a local replay inbox.
        inbox=self.endpoint.receive_available();allocation=[]
        for msg in inbox:
            if msg.mission_id!='phase8':continue
            p=msg.payload;used=False
            if msg.sender_id in self.peer_health and msg.message_type==MT.HEARTBEAT:
                previous=self.peer_health[msg.sender_id].state
                self.peer_health[msg.sender_id].heartbeat(msg.timestamp)
                if previous!=self.peer_health[msg.sender_id].state:
                    self.log('peer_health_changed',now,peer=msg.sender_id,previous=previous.value,state=self.peer_health[msg.sender_id].state.value)
                allocation.append(msg);used=True
            elif msg.message_type==MT.TARGET_FOUND and msg.sender_id in self.peer_health:
                from agentic_uav.coordination.contract_net import MissionTask
                task=MissionTask.from_dict(p['task'])
                if task.priority>=self.critical_priority and task.task_type==TaskType.INSPECT_TARGET and task.task_id not in self.tasks:
                    self.tasks[task.task_id]=task;used=True
                    self.log('critical_task_received',now,task_id=task.task_id,source=msg.sender_id)
            elif msg.sender_id in self.peer_health and msg.message_type in (MT.STATUS_UPDATE,MT.ROLE_CHANGE):
                if 'role' in p:
                    try:Role(p['role'])
                    except ValueError:continue
                self.peer_status.setdefault(msg.sender_id,{}).update(p);used=True
            elif msg.message_type==MT.MISSION_UPDATE and msg.sender_id==self.supervisor_id and p.get('kind')=='confirmed_failure' and p.get('agent_id') in self.peer_health:
                peer=p['agent_id'];self.peer_health[peer].confirmed_failure()
                self.log('peer_health_changed',now,peer=peer,state=Health.FAILED.value,source='trusted_supervisor');used=True
            elif msg.message_type==MT.TASK_RELEASE and p.get('reason')=='bid_withdrawn':
                self.bids.get(p.get('task_id'),{}).pop(msg.sender_id,None);used=True
            else:allocation.append(msg)
            if used:self.decisions.append(msg.message_id)
        # Supply only already-delivered addressed allocation messages, never another agent's memory.
        endpoint=self.endpoint
        class Inbox:
            def receive_available(inner):return allocation
            def send(inner,msg):return endpoint.send(msg)
        self.endpoint=Inbox()
        try:super().receive(now)
        finally:self.endpoint=endpoint

    def discover_target(self,task,now):
        if task.task_type!=TaskType.INSPECT_TARGET or task.priority<self.critical_priority:
            raise ValueError('Expected a high-priority inspection task')
        if task.task_id in self.tasks:return
        self.tasks[task.task_id]=task
        self.send(MT.TARGET_FOUND,dict(task=task.to_dict()),now)
        self.log('critical_target_discovered',now,task_id=task.task_id)

    def offer(self,task,now):
        if self.quarantined or self.battery<self.low_battery:return
        if self.objective=='CRITICAL_ONLY' and task.priority<self.critical_priority:return
        if self.role==Role.RESERVE:return
        if self.role==Role.RELAY and task.task_type not in (TaskType.MAINTAIN_RELAY,TaskType.RETURN_TO_BASE):return
        # Parent role penalty uses lowercase functional names.
        saved=self.role
        self.role='relay' if saved==Role.RELAY else ('inspector' if task.task_type==TaskType.INSPECT_TARGET else 'searcher')
        try:super().offer(task,now)
        finally:self.role=saved

    def change_role(self,new,reason,now):
        new=Role(new)
        if new==self.role:return
        previous=self.role;self.role=new
        for task in list(self.tasks.values()):
            if task.assigned_agent==self.agent_id and task.status==TaskStatus.ASSIGNED and new!=Role.SCOUT:
                self.release_task(task.task_id,now)
        for task in self.tasks.values():
            incompatible=(new==Role.RESERVE or (new==Role.RELAY and task.task_type not in (TaskType.MAINTAIN_RELAY,TaskType.RETURN_TO_BASE)))
            if incompatible and self.agent_id in self.bids.get(task.task_id,{}):
                self.bids[task.task_id].pop(self.agent_id,None)
                self.send(MT.TASK_RELEASE,dict(task_id=task.task_id,version=task.version,reason='bid_withdrawn'),now)
        self.send(MT.ROLE_CHANGE,dict(role=new.value,previous_role=previous.value,reason=reason),now)
        self.log('role_changed',now,previous=previous.value,role=new.value,reason=reason)
        # Rebid already-open tasks when a reserve becomes available.
        for task in self.tasks.values():
            if task.status==TaskStatus.BIDDING:self.offer(task,now)

    def policy(self,now):
        for peer,belief in self.peer_health.items():
            previous=belief.state;belief.tick(now)
            if previous!=belief.state:self.log('peer_health_changed',now,peer=peer,previous=previous.value,state=belief.state.value)
        unavailable={p for p,h in self.peer_health.items() if h.state in (Health.UNREACHABLE,Health.FAILED,Health.RECOVERED)}
        if len(unavailable)>=2 and self.objective!='CRITICAL_ONLY':
            self.objective='CRITICAL_ONLY'
            self.log('mission_reprioritized',now,objective=self.objective,reason='fewer_than_three_responsive_agents')
            self.send(MT.MISSION_UPDATE,dict(objective=self.objective,reason='reduced_team_capacity'),now)
            for task in list(self.tasks.values()):
                if task.priority<self.critical_priority and task.assigned_agent==self.agent_id and task.status==TaskStatus.ASSIGNED:
                    self.release_task(task.task_id,now)
        if self.battery<self.low_battery or self.quarantined:
            self.change_role(Role.RESERVE,'low_battery' if not self.quarantined else 'rejoin_quarantine',now)
            return
        candidates=[]
        for agent in [self.agent_id]+self.peers:
            if agent in unavailable:continue
            state=(dict(role=self.role.value,battery=self.battery,position=self.position) if agent==self.agent_id else
                   self.peer_status.get(agent,dict(role=self.initial_roles[agent].value,battery=100.,position=self.relay_point)))
            if state.get('battery',0)<self.low_battery:continue
            role=Role(state.get('role',self.initial_roles[agent]))
            # Preserve a healthy relay; otherwise prefer reserve, then scout; deterministic ID tie-break.
            rank={Role.RELAY:0,Role.RESERVE:1,Role.SCOUT:2}[role]
            candidates.append((rank,math.dist(state.get('position',self.relay_point),self.relay_point),agent))
        relay=min(candidates)[2] if candidates else None
        if relay==self.agent_id:
            self.change_role(Role.RELAY,'relay_election',now)
            self.position=list(self.relay_point)  # Mock positioning only.
        elif self.role==Role.RELAY:
            self.change_role(Role.SCOUT,'another_relay_preferred',now)
        elif self.role==Role.RESERVE and (unavailable or any(self.peer_status.get(p,{}).get('battery',100.)<self.low_battery and self.initial_roles[p]==Role.SCOUT for p in self.peers) or any(t.priority>=self.critical_priority and t.status!=TaskStatus.COMPLETE for t in self.tasks.values())):
            self.change_role(Role.SCOUT,'peer_disruption_or_critical_task',now)

    def step(self,now,dt,process_inbox=True,execute_mock=True):
        if process_inbox:self.receive(now)
        self.policy(now)
        self.send(MT.STATUS_UPDATE,dict(role=self.role.value,battery=self.battery,position=list(self.position),
            workload=self.workload(),objective=self.objective),now)
        super().step(now,dt,process_inbox=False,execute_mock=execute_mock)
