"""Phase 12 mock and optional live execution adapters. No policy state sharing."""
import math
import threading
import time


class MockFlight:
    def __init__(self,vehicles,clock):
        self.clock=clock
        self.states={a:dict(position=list(v['start_position']),velocity=[0.,0.,0.],battery=80.,phase='AIRBORNE') for a,v in vehicles.items()}
        self.active={};self.effects=[]

    def sample(self,agent_id):return dict(self.states[agent_id])

    def execute(self,action):
        if action.kind in ('MOVE','TAKEOFF') and len(action.waypoints)!=1:raise ValueError('Adapter requires one validated segment per dispatch')
        state=self.states[action.vehicle_id]
        target=(list(action.waypoints[-1]) if action.kind in ('MOVE','TAKEOFF') else
                list(state['home']) if action.kind=='RETURN_HOME' else
                [state['position'][0],state['position'][1],state['ground_z']] if action.kind=='LAND' else list(state['position']))
        self.active[action.vehicle_id]=dict(action=action,target=target,start=self.clock())
        effect=dict(time_s=self.clock(),vehicle_id=action.vehicle_id,command_id=action.command_id,kind=action.kind,target=target)
        self.effects.append(effect)
        return dict(executed=True,completed=False,status='mock_active')

    def cancel(self,vehicle_id):
        self.active.pop(vehicle_id,None);self.states[vehicle_id]['velocity']=[0.,0.,0.];return True

    def advance(self,dt):
        completed=[]
        for vehicle,job in list(self.active.items()):
            a=job['action'];s=self.states[vehicle];target=job['target'];distance=math.dist(s['position'],target)
            delta=min(distance,a.speed_mps*dt)
            if distance:
                s['velocity']=[(target[i]-s['position'][i])/distance*a.speed_mps for i in range(3)]
                s['position']=[s['position'][i]+(target[i]-s['position'][i])*delta/distance for i in range(3)]
                s['battery']=max(0,s['battery']-.01*delta)
            reached=math.dist(s['position'],target)<1e-8
            done=(reached and (a.kind!='HOLD' or self.clock()-job['start']>=a.duration_s-1e-8))
            if done:
                s['velocity']=[0.,0.,0.]
                if a.kind=='LAND':s['phase']='GROUNDED'
                completed.append((vehicle,a.command_id));self.active.pop(vehicle,None)
        return completed


class AirSimFlight:
    def __init__(self,vehicles,clock,host='127.0.0.1',rpc_timeout=2.,ground_z=0.):
        import airsim
        self.lock=threading.RLock();self.ground_z=ground_z;self.airsim=airsim;self.vehicles=vehicles;self.clock=clock;self.host=host;self.timeout=rpc_timeout
        self.reader=airsim.MultirotorClient(ip=host,timeout_value=rpc_timeout);self.reader.confirmConnection()
        missing=set(vehicles)-set(self.reader.listVehicles())
        if missing:raise ValueError('Missing AirSim vehicles: '+str(sorted(missing)))
        self.commanders={a:airsim.MultirotorClient(ip=host,timeout_value=rpc_timeout) for a in vehicles}
        self.active={};self.effects=[];self.takeoff_errors={};self.controlled=set()

    def sample(self,agent_id):
        raw=self.reader.getMultirotorState(vehicle_name=agent_id)
        p=raw.kinematics_estimated.position;v=raw.kinematics_estimated.linear_velocity
        offset=self.vehicles[agent_id]['frame_offset_m']
        landed=raw.landed_state==self.airsim.LandedState.Landed
        battery=getattr(raw,'battery_remaining',None)
        # SimpleFlight commonly has no battery telemetry. Never invent a reserve.
        if battery is None:
            battery=self.vehicles[agent_id].get('assumed_battery_percent')
            if battery is None:raise ValueError('Missing battery telemetry; configure explicit test battery assumption')
        return dict(position=[p.x_val+offset[0],p.y_val+offset[1],p.z_val+offset[2]],
            velocity=[v.x_val,v.y_val,v.z_val],battery=float(battery),phase='GROUNDED' if landed else 'AIRBORNE')

    def execute(self,action):
        a=action.vehicle_id;c=self.commanders[a];offset=self.vehicles[a]['frame_offset_m']
        if action.kind in ('MOVE','TAKEOFF') and len(action.waypoints)!=1:raise ValueError('Adapter requires one validated segment per dispatch')
        position=self.sample(a)['position']
        target=(list(action.waypoints[-1]) if action.kind in ('MOVE','TAKEOFF') else
            list(self.vehicles[a]['home']) if action.kind=='RETURN_HOME' else
            [position[0],position[1],self.ground_z] if action.kind=='LAND' else position)
        token=object();job=dict(action=action,target=target,start=self.clock(),token=token);self.active[a]=job
        if action.kind=='TAKEOFF':
            # Only invoked after the whole takeoff corridor is approved.
            c.enableApiControl(True,vehicle_name=a);c.armDisarm(True,vehicle_name=a);self.controlled.add(a)
            def takeoff():
                try:
                    client=self.airsim.MultirotorClient(ip=self.host,timeout_value=max(35.,self.timeout))
                    client.takeoffAsync(timeout_sec=30,vehicle_name=a).join()
                    with self.lock:
                        if self.active.get(a,{}).get('token') is token:
                            local=[target[i]-offset[i] for i in range(3)]
                            client.moveToPositionAsync(*local,velocity=action.speed_mps,timeout_sec=30,vehicle_name=a)
                except Exception as e:self.takeoff_errors[a]=type(e).__name__
            threading.Thread(target=takeoff,daemon=True).start()
        elif action.kind=='HOLD':c.hoverAsync(vehicle_name=a)
        elif action.kind=='LAND':c.landAsync(timeout_sec=30,vehicle_name=a)
        else:
            local=[target[i]-offset[i] for i in range(3)]
            c.moveToPositionAsync(*local,velocity=action.speed_mps,timeout_sec=30,vehicle_name=a)
        self.effects.append(dict(time_s=self.clock(),vehicle_id=a,command_id=action.command_id,kind=action.kind,target=target))
        return dict(executed=True,completed=False,status='airsim_requested')

    def cancel(self,vehicle_id):
        with self.lock:return self._cancel_locked(vehicle_id)

    def _cancel_locked(self,vehicle_id):
        # Invalidate any setup continuation before issuing cancellation.
        old=self.active.get(vehicle_id)
        if old:old['token']=None
        try:
            c=self.commanders[vehicle_id];c.cancelLastTask(vehicle_name=vehicle_id);c.hoverAsync(vehicle_name=vehicle_id)
            s=self.sample(vehicle_id)
            if math.sqrt(sum(v*v for v in s['velocity']))>.3:return False
            self.active.pop(vehicle_id,None);return True
        except Exception:return False

    def advance(self,dt):
        completed=[]
        for a,job in list(self.active.items()):
            if a in self.takeoff_errors:raise RuntimeError('Takeoff RPC failed: '+a+':'+self.takeoff_errors[a])
            s=self.sample(a);action=job['action']
            if action.kind=='HOLD':done=self.clock()-job['start']>=action.duration_s and math.sqrt(sum(v*v for v in s['velocity']))<.3
            elif action.kind=='LAND':done=s['phase']=='GROUNDED'
            else:done=math.hypot(s['position'][0]-job['target'][0],s['position'][1]-job['target'][1])<=.4 and abs(s['position'][2]-job['target'][2])<=.6 and math.sqrt(sum(v*v for v in s['velocity']))<.3
            if done:
                completed.append((a,action.command_id));self.active.pop(a,None)
        return completed
