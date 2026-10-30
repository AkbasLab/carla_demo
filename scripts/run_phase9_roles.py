"""Phase 9 dynamic role/failure-recovery mock benchmark. No LLM or live radio model."""
import argparse
import json
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.comm.protocol import PerfectMessageBus
from agentic_uav.coordination.contract_net import MissionTask,TaskType,TaskStatus,Geometry
from agentic_uav.coordination.dynamic_roles import DynamicRoleAgent,Role


def run(ticks=600,dt=.1,output_dir='results/phase9/roles',fail_agent='Drone1',fail_at=2.,
        low_battery_agent=None,low_battery_at=2.,critical_task=False,target_at=5.,network_config=None,seed=42):
    ids=[f'Drone{i}' for i in range(1,5)]
    roles=dict(zip(ids,['SCOUT','SCOUT','RELAY','RESERVE']))
    tasks=[MissionTask('SEARCH_SECTOR_'+letter,TaskType.SEARCH_SECTOR,Geometry((x,y,-3)),1,{'search'},work_units=8.)
           for letter,(x,y) in zip('ABCD',[(0,0),(10,0),(0,10),(10,10)])]
    target_reported=False
    time=[0.]
    endpoints={}
    if network_config is None:bus=PerfectMessageBus(ids,lambda:time[0])
    else:
        from agentic_uav.comm.degraded import DegradedMessageBus,ObservedEndpoint
        bus=DegradedMessageBus(ids,lambda:time[0],network_config,seed,
            positions=lambda aid: next(a.position for a in agents if a.agent_id==aid))
        endpoints={aid:ObservedEndpoint(bus.endpoint(aid),aid,lambda:time[0],mission_lifetime_s=ticks*dt+1) for aid in ids}
    agents=[DynamicRoleAgent(a,[p for p in ids if p!=a],endpoints.get(a) or bus.endpoint(a),tasks,position,
            initial_roles=roles,lease_s=3.,bid_window=.3,relay_point=(5,5,-3))
            for a,position in zip(ids,[(0,0,-3),(10,0,-3),(5,5,-3),(10,10,-3)])]
    failed=set();trace=[];active=[];complete=False
    for tick in range(ticks):
        time[0]=round(tick*dt,8)
        if fail_agent and time[0]>=fail_at:failed.add(fail_agent)
        active=[a for a in agents if a.agent_id not in failed]
        if critical_task and not target_reported and time[0]>=target_at and active:
            observer=next((a for a in active if a.agent_id=='Drone2'),active[0])
            observer.discover_target(MissionTask('INSPECT_TARGET_T1',TaskType.INSPECT_TARGET,Geometry((5,5,-3)),10,{'inspect'},work_units=3.),time[0])
            target_reported=True
        for a in active:
            if a.agent_id==low_battery_agent and time[0]>=low_battery_at:a.battery=15.
            a.receive(time[0])
        for a in active:
            a.step(time[0],dt,process_inbox=False)
            for mid in a.decisions:bus.record_decision(a.agent_id,mid)
            a.decisions.clear()
            trace.append(dict(time_s=time[0],agent_id=a.agent_id,role=a.role.value,position=a.position[:],
                battery=a.battery,objective=a.objective,communication_health=endpoints[a.agent_id].estimates() if endpoints else {},peer_health={p:h.state.value for p,h in a.peer_health.items()},
                peer_status=json.loads(json.dumps(a.peer_status)),tasks=[t.to_dict() for t in a.tasks.values()]))
        if active and all(all(t.status==TaskStatus.COMPLETE for t in a.tasks.values()) for a in active):complete=True;break
    events=sorted([e for a in agents for e in a.events],key=lambda e:(e['time_s'],e['agent_id']))
    completed=[e for e in events if e['event']=='work_completed']
    summary=dict(mode='phase9_dynamic_roles_mock',llm=False,mission_complete=complete,time_s=time[0],
        failed_agent_injection=fail_agent,fail_at_s=fail_at if fail_agent else None,
        initial_roles=roles,final_roles={a.agent_id:a.role.value for a in active},
        completions_by_agent={a:sum(e['agent_id']==a for e in completed) for a in ids},
        duplicate_task_completions=len(completed)-len({e['task_id'] for e in completed}),
        role_changes=sum(e['event']=='role_changed' for e in events),
        health_transitions=sum(e['event']=='peer_health_changed' for e in events),
        lease_expirations=len({(e['task_id'],e['version']) for e in events if e['event']=='lease_expired'}),
        final_peer_health={a.agent_id:{p:h.state.value for p,h in a.peer_health.items()} for a in active},
        limitations=['Mock role positioning/task work only; live four-drone execution not integrated',
            'Relay election maintains a designated role; no RF reachability/throughput improvement is measured',
            'Silence becomes UNREACHABLE, never confirmed FAILED without supervisor evidence',
            'Health RECOVERED does not authorize safe rejoin of old task epochs; rejoin execution not supported',
            'Fixed membership and trusted perfect messaging; not partition consensus'])
    if network_config is not None:
        from dataclasses import asdict
        from collections import Counter
        summary.update(mode='phase10_degraded_communications_mock',seed=seed,network_config=asdict(network_config),
            replay_parameters=dict(ticks=ticks,dt=dt,fail_agent=fail_agent,fail_at=fail_at,critical_task=critical_task,target_at=target_at),
            network_outcomes=dict(Counter(r['status'] for r in bus.logs())),
            network_drop_reasons=dict(Counter(r['drop_reason'] for r in bus.logs() if r.get('drop_reason'))),
            final_communication_estimates={a.agent_id:endpoints[a.agent_id].estimates() for a in active})
        summary['limitations'][-1]='Fixed membership and trusted peers; allocation is not partition consensus'
        summary['limitations'].append('Application-level network model; not calibrated RF. ACK RTT includes peer scheduling. Pending messages at mission stop are censored.')
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    for name,data in dict(summary=summary,events=events,beliefs=trace,messages=bus.logs()).items():
        (out/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps(summary,indent=2));return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ticks',type=int,default=600);p.add_argument('--dt',type=float,default=.1)
    p.add_argument('--output-dir',default='results/phase9/roles')
    p.add_argument('--fail-agent',choices=['none','Drone1','Drone2','Drone3','Drone4'],default='Drone1')
    p.add_argument('--fail-at',type=float,default=2.)
    p.add_argument('--low-battery-agent',choices=['Drone1','Drone2','Drone3','Drone4'])
    p.add_argument('--low-battery-at',type=float,default=2.)
    p.add_argument('--critical-task',action='store_true')
    p.add_argument('--target-at',type=float,default=5.)
    a=p.parse_args()
    if a.ticks<1 or not math.isfinite(a.dt) or a.dt<=0 or any(not math.isfinite(v) or v<0 for v in [a.fail_at,a.low_battery_at,a.target_at]):p.error('Invalid timing')
    run(a.ticks,a.dt,a.output_dir,None if a.fail_agent=='none' else a.fail_agent,a.fail_at,a.low_battery_agent,a.low_battery_at,a.critical_task,a.target_at)
