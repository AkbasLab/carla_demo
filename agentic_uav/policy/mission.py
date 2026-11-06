"""Shared Phase 12/13 mission and safety-configuration loader."""
import json
import math
from pathlib import Path
import re
from agentic_uav.control.runtime_guardian import Config
from agentic_uav.coordination.contract_net import MissionTask,TaskType,TaskStatus,Geometry


def load_mission(path, *, allowed_team_sizes=(4,)):
    m=json.loads(Path(path).read_text());config=Config(**m['guardian'])
    def vector(v):return isinstance(v,list) and len(v)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in v)
    if not isinstance(m['mission'],str) or not 0<len(m['mission'])<=4000:raise ValueError('Mission text required')
    if not isinstance(m['vehicles'],dict) or len(m['vehicles']) not in allowed_team_sizes:raise ValueError('Unsupported mission team size: '+str(allowed_team_sizes))
    for a,v in m['vehicles'].items():
        if not re.fullmatch('[A-Za-z0-9_-]{1,64}',a) or v['role'] not in ('SCOUT','RELAY','RESERVE') or not all(vector(v[k]) for k in ['start_position','home','frame_offset_m']):raise ValueError('Invalid vehicle configuration')
    if not vector(m['relay_point']):raise ValueError('Invalid relay point')
    tasks=[];routes={}
    if not 1<=len(m['tasks'])<=32:raise ValueError('Require 1–32 tasks for bounded context')
    for item in m['tasks']:
        tid=item['task_id'];route=item['waypoints']
        if not isinstance(tid,str) or not tid or tid in routes or not route or not all(vector(p) for p in route):raise ValueError('Invalid task route')
        routes[tid]=route
        center=tuple(sum(p[i] for p in route)/len(route) for i in range(3))
        tasks.append(MissionTask(tid,TaskType.SEARCH_SECTOR,Geometry(center),item.get('priority',1),{'search'},work_units=len(route)))
    return m,config,tasks,routes
