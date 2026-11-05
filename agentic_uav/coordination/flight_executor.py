"""Observed waypoint execution, resumable checkpoints, and bounded stalled-command retries."""
import math


def arrival_errors(position,target):
    return math.hypot(position[0]-target[0],position[1]-target[1]),abs(position[2]-target[2])


def within_waypoint(position,target,xy_tolerance,z_tolerance=None):
    if z_tolerance is None:return math.dist(position,target)<=xy_tolerance
    xy,z=arrival_errors(position,target)
    return xy<=xy_tolerance and z<=z_tolerance


class WaypointExecutor:
    def __init__(self,routes,tolerance=.4,progress_distance=.1,*,z_tolerance=None,stall_timeout=4.,max_retries=2):
        self.routes=routes;self.tolerance=tolerance;self.z_tolerance=z_tolerance
        self.progress_distance=progress_distance;self.stall_timeout=stall_timeout;self.max_retries=max_retries
        self.key=None;self.index=0;self.last_report=-math.inf;self.arrivals=[]
        self.best_distance=None;self.last_improvement=0.;self.retry_time=0.;self.retries=0

    def update(self,agent,now):
        task=agent.executable_task(now)
        if task is None:
            previous=self.key;self.key=None
            return dict(action='hold',revoked=previous is not None)
        key=(task.task_id,task.version);route=self.routes[task.task_id]
        if key!=self.key:
            self.key=key;self.index=min(agent.checkpoints.get(task.task_id,0),len(route))
            self.last_report=now;self.last_improvement=now;self.retry_time=now;self.retries=0
            self.best_distance=math.dist(agent.position,route[self.index]) if self.index<len(route) else 0.
            agent.report_execution(*key,now,self.index/len(route),completed_waypoints=self.index)
            agent.log('execution_started',now,task_id=task.task_id,version=task.version,resume_index=self.index)
        reached=False
        if self.index<len(route) and within_waypoint(agent.position,route[self.index],self.tolerance,self.z_tolerance):
            xy,z=arrival_errors(agent.position,route[self.index])
            self.arrivals.append(dict(time_s=now,agent_id=agent.agent_id,task_id=task.task_id,
                version=task.version,index=self.index,position=list(agent.position),target=list(route[self.index]),
                xy_error_m=xy,z_error_m=z))
            agent.log('waypoint_arrived',now,task_id=task.task_id,version=task.version,index=self.index,xy_error_m=xy,z_error_m=z)
            self.index+=1;reached=True;self.retries=0
        if self.index==len(route):
            agent.report_execution(*key,now,1.,complete=True,completed_waypoints=self.index)
            self.key=None
            return dict(action='hold',complete=True)
        distance=math.dist(agent.position,route[self.index])
        improved=reached or self.best_distance-distance>=self.progress_distance
        if improved:
            self.best_distance=distance;self.last_improvement=now
        if reached or (now-self.last_report>=agent.lease_s/3 and self.last_improvement>self.last_report):
            agent.report_execution(*key,now,self.index/len(route),completed_waypoints=self.index)
            self.last_report=now
        xy,z=arrival_errors(agent.position,route[self.index])
        action=dict(action='move',target=route[self.index],task_id=task.task_id,version=task.version,index=self.index,
                    xy_error_m=xy,z_error_m=z,retry=self.retries)
        if now-max(self.last_improvement,self.retry_time)>=self.stall_timeout and self.retries<self.max_retries:
            self.retries+=1;self.retry_time=now;action['retry']=self.retries
            agent.log('waypoint_command_retry',now,task_id=task.task_id,version=task.version,index=self.index,
                      retry=self.retries,xy_error_m=xy,z_error_m=z)
        return action
