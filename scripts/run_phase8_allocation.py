"""Four-agent deterministic contract-net mock benchmark. No LLM or live flight."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.comm.protocol import PerfectMessageBus
from agentic_uav.coordination.contract_net import AllocationAgent, MissionTask, Geometry, TaskType, TaskStatus


def run(ticks=300,dt=.1,output_dir='results/phase8/allocation',inject_conflict=True,fail_agent=None,fail_at=1.5):
    ids=[f'Drone{i}' for i in range(1,5)]
    tasks=[MissionTask(f'SEARCH_SECTOR_{letter}',TaskType.SEARCH_SECTOR,Geometry((x,y,-3)),1,{'search'},work_units=3.)
           for letter,(x,y) in zip('ABCD',[(0,0),(10,0),(0,10),(10,10)])]
    starts=[(0,0,-3),(10,0,-3),(0,10,-3),(10,10,-3)]
    clock=[0.]
    bus=PerfectMessageBus(ids,lambda:clock[0])
    agents=[AllocationAgent(a,[p for p in ids if p!=a],bus.endpoint(a),tasks,position,
                           inject_conflict=inject_conflict) for a,position in zip(ids,starts)]
    traces=[];active=[]
    for tick in range(ticks):
        clock[0]=round(tick*dt,9)
        active=[a for a in agents if not (a.agent_id==fail_agent and clock[0]>=fail_at)]
        # Stage inbox consumption before decisions to avoid scheduler-order arbitration.
        for agent in active:agent.receive(clock[0])
        for agent in active:
            agent.step(clock[0],dt,process_inbox=False)
            for message_id in agent.decisions:bus.record_decision(agent.agent_id,message_id)
            agent.decisions.clear()
            traces.append(dict(time_s=clock[0],agent_id=agent.agent_id,position=agent.position[:],
                               tasks=[t.to_dict() for t in agent.tasks.values()]))
        if active and all(all(t.status==TaskStatus.COMPLETE for t in a.tasks.values()) for a in active):break
    logs=bus.logs()
    events=[e for a in agents for e in a.events]
    events.sort(key=lambda e:(e['time_s'],e['agent_id']))
    completions=[e for e in events if e['event']=='work_completed']
    result=dict(mode='phase8_decentralized_contract_net_mock',llm=False,
        mission_complete=bool(active and all(all(t.status==TaskStatus.COMPLETE for t in a.tasks.values()) for a in active)),
        time_s=clock[0],completed_task_ids=sorted({e['task_id'] for e in completions}),
        completions_by_agent={a:sum(e['agent_id']==a for e in completions) for a in ids},
        duplicate_task_completions=len(completions)-len({e['task_id'] for e in completions}),
        conflict_corrections=sum(e['event']=='claim_corrected' for e in events),
        lease_expirations=len({(e['task_id'],e['version']) for e in events if e['event']=='lease_expired'}),
        local_lease_expiration_events=sum(e['event']=='lease_expired' for e in events),
        fail_agent=fail_agent,fail_at_s=fail_at if fail_agent else None,
        message_instances=len({m['message_id'] for m in logs}),recipient_records=len(logs),
        limitations=['Mock task work and positions; not physical sector coverage or live flight',
                     'Known team membership, perfect transport, trusted deterministic peers',
                     'Silent-agent suspicion uses heartbeat age; not distributed consensus under network partitions',
                     'Task progress renews leases via INTENT_UPDATE; protocol has no TASK_PROGRESS type'])
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    for name,data in [('summary',result),('tasks',[t.to_dict() for t in tasks]),('events',events),('beliefs',traces),('messages',logs)]:
        (out/(name+'.json')).write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ticks',type=int,default=300)
    p.add_argument('--dt',type=float,default=.1)
    p.add_argument('--output-dir',default='results/phase8/allocation')
    p.add_argument('--no-conflict-injection',action='store_true')
    p.add_argument('--fail-agent',choices=['Drone1','Drone2','Drone3','Drone4'])
    p.add_argument('--fail-at',type=float,default=1.5)
    a=p.parse_args()
    import math
    if a.ticks<1 or not math.isfinite(a.dt) or a.dt<=0 or not math.isfinite(a.fail_at) or a.fail_at<0:p.error('Invalid timing')
    run(a.ticks,a.dt,a.output_dir,not a.no_conflict_injection,a.fail_agent,a.fail_at)
