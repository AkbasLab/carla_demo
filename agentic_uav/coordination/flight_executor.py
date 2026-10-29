"""Own-vehicle waypoint observations drive task progress; no elapsed-time completion."""
import math


class WaypointExecutor:
    def __init__(self, routes, tolerance=.4, progress_distance=.1):
        self.routes=routes;self.tolerance=tolerance;self.progress_distance=progress_distance
        self.key=None;self.index=0;self.last_position=None
        self.last_report=-math.inf;self.arrivals=[];self.last_distance=None

    def update(self,agent,now):
        task=agent.executable_task(now)
        if task is None:
            previous=self.key;self.key=None
            return dict(action='hold',revoked=previous is not None)
        key=(task.task_id,task.version)
        if key!=self.key:
            self.key=key;self.index=0;self.last_position=list(agent.position);self.last_report=now
            self.last_distance=math.dist(agent.position,self.routes[task.task_id][0])
            agent.report_execution(*key,now,0.)
        route=self.routes[task.task_id]
        reached=False
        if math.dist(agent.position,route[self.index])<=self.tolerance:
            self.arrivals.append(dict(time_s=now,agent_id=agent.agent_id,task_id=task.task_id,
                                     version=task.version,index=self.index,position=list(agent.position)))
            self.index+=1;reached=True
        if self.index==len(route):
            agent.report_execution(*key,now,1.,complete=True)
            self.key=None
            return dict(action='hold',complete=True)
        distance=math.dist(agent.position,route[self.index])
        moved=self.last_distance-distance>=self.progress_distance
        if reached or (moved and now-self.last_report>=agent.lease_s/3):
            agent.report_execution(*key,now,self.index/len(route))
            self.last_position=list(agent.position);self.last_report=now;self.last_distance=distance
        return dict(action='move',target=route[self.index],task_id=task.task_id,version=task.version,index=self.index)
