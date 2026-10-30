"""Four-agent contract-net benchmark: mock or live CARLAAir, without an LLM."""
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
    p.add_argument('--backend',choices=['mock','airsim'],default='mock')
    p.add_argument('--mission-config',help='Required for AirSim; shared NED waypoints and per-vehicle offsets')
    p.add_argument('--route-scale',type=float,default=1.,help='Scale shared mission waypoint X/Y, preserving Z and vehicle offsets')
    p.add_argument('--overview-camera',action='store_true',help='Frame routes and four starts in CARLA spectator; draw waypoint labels')
    p.add_argument('--carla-frame-origin',nargs=3,type=float,metavar=('X','Y','Z'),help='CARLA position of shared NED origin, assuming aligned X/Y and inverted Z')
    p.add_argument('--camera-height',type=float,default=40.,help='Minimum overhead camera height above mission routes')
    p.add_argument('--airsim-host',default='127.0.0.1')
    p.add_argument('--carla-host',default=None)
    p.add_argument('--carla-port',type=int,default=2000)
    p.add_argument('--lease-seconds',type=float,default=10.)
    p.add_argument('--bid-window',type=float,default=1.)
    p.add_argument('--flight-height',type=float,default=3.)
    p.add_argument('--speed',type=float,default=1.)
    p.add_argument('--arrival-tolerance',type=float,default=.4,help='Horizontal waypoint tolerance (meters) in live mode')
    p.add_argument('--altitude-tolerance',type=float,default=.6,help='Independent vertical arrival tolerance (meters)')
    p.add_argument('--stall-timeout',type=float,default=4.,help='Seconds without distance improvement before retrying the current valid movement')
    p.add_argument('--max-waypoint-retries',type=int,default=2)
    p.add_argument('--rpc-timeout',type=float,default=15.)
    p.add_argument('--setup-timeout',type=float,default=120.)
    p.add_argument('--waypoint-timeout',type=float,default=60.)
    p.add_argument('--landing-confirm-timeout',type=float,default=15.)
    p.add_argument('--ticks',type=int,default=300)
    p.add_argument('--dt',type=float,default=.1)
    p.add_argument('--output-dir',default='results/phase8/allocation')
    p.add_argument('--no-conflict-injection',action='store_true')
    p.add_argument('--fail-agent',choices=['Drone1','Drone2','Drone3','Drone4'])
    p.add_argument('--fail-at',type=float,default=1.5)
    a=p.parse_args()
    import math
    if a.ticks<1 or not math.isfinite(a.dt) or a.dt<=0 or not math.isfinite(a.fail_at) or a.fail_at<0:p.error('Invalid timing')
    for value in (a.altitude_tolerance,a.stall_timeout,a.route_scale,a.camera_height,a.lease_seconds,a.bid_window,a.flight_height,a.speed,a.arrival_tolerance,a.rpc_timeout,a.setup_timeout,a.waypoint_timeout,a.landing_confirm_timeout):
        if not math.isfinite(value) or value<=0:p.error('Flight parameters must be finite and positive')
    if a.max_waypoint_retries<0:p.error('--max-waypoint-retries must be nonnegative')
    if a.overview_camera and (a.backend!='airsim' or not a.carla_host or a.carla_frame_origin is None):
        p.error('--overview-camera requires --backend airsim --carla-host and calibrated --carla-frame-origin X Y Z')
    if a.carla_frame_origin is not None and not all(math.isfinite(v) for v in a.carla_frame_origin):
        p.error('Camera frame origin must be finite')
    if a.backend=='airsim':
        if not a.mission_config:p.error('--mission-config is required for AirSim')
        from agentic_uav.coordination.phase8_live import run_live
        run_live(a)
    else:
        run(a.ticks,a.dt,a.output_dir,not a.no_conflict_injection,a.fail_agent,a.fail_at)
