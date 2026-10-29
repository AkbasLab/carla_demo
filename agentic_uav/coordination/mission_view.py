"""Scene visualization only: explicit shared-NED to CARLA translation, no agent inputs."""
import copy
import math


def scale_routes(config, factor):
    """Scale XY about shared mission origin; preserve NED Z and vehicle frame offsets."""
    if not math.isfinite(factor) or factor<=0:raise ValueError('Route scale must be finite and positive')
    result=copy.deepcopy(config)
    for task in result['tasks']:
        task['waypoints']=[[p[0]*factor,p[1]*factor,p[2]] for p in task['waypoints']]
    return result


def overview_geometry(points,origin,height):
    if not points:raise ValueError('Need routes and starting positions to frame')
    transformed=[(origin[0]+p[0],origin[1]+p[1],origin[2]-p[2]) for p in points]
    xmin,xmax=min(p[0] for p in transformed),max(p[0] for p in transformed)
    ymin,ymax=min(p[1] for p in transformed),max(p[1] for p in transformed)
    span=max(xmax-xmin,ymax-ymin)
    return ((xmin+xmax)/2,(ymin+ymax)/2,max(p[2] for p in transformed)+max(height,span*1.2+10))


def draw_overview(world,carla,routes,starts,origin,height,lifetime):
    points=[p for route in routes.values() for p in route]+list(starts.values())
    camera=overview_geometry(points,origin,height)
    world.get_spectator().set_transform(carla.Transform(carla.Location(*camera),carla.Rotation(pitch=-90,yaw=0,roll=0)))
    palette=[(255,80,80),(80,220,80),(80,160,255),(255,200,40)]
    def location(p):return carla.Location(x=origin[0]+p[0],y=origin[1]+p[1],z=origin[2]-p[2]+.3)
    for index,(task,route) in enumerate(routes.items()):
        color=carla.Color(*palette[index%len(palette)])
        for number,p in enumerate(route):
            where=location(p)
            world.debug.draw_point(where,size=.2,color=color,life_time=lifetime)
            world.debug.draw_string(where,f'{task} WP{number+1} ({p[0]:.1f}, {p[1]:.1f}, Z={p[2]:.1f})',
                                    draw_shadow=True,color=color,life_time=lifetime)
            if number:world.debug.draw_line(location(route[number-1]),where,thickness=.08,color=color,life_time=lifetime)
    for name,p in starts.items():
        world.debug.draw_string(location(p),f'{name} START',draw_shadow=True,color=carla.Color(255,255,255),life_time=lifetime)
    return camera


def save_route_map(routes,starts,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,8),constrained_layout=True)
    try:
        for task,route in routes.items():
            line,=ax.plot([p[0] for p in route],[p[1] for p in route],'-o',label=task)
            for index,p in enumerate(route,1):
                ax.annotate(f'WP{index}\n({p[0]:g}, {p[1]:g})',(p[0],p[1]),xytext=(5,5),textcoords='offset points',fontsize=8,color=line.get_color())
        for name,p in starts.items():
            ax.scatter(p[0],p[1],marker='x',color='black',s=65)
            ax.annotate(name+' start',(p[0],p[1]),xytext=(5,-12),textcoords='offset points',fontsize=8)
        ax.set(xlabel='Shared mission X (m)',ylabel='Shared mission Y (m)',
               title='Phase 8 route plan and drone starting positions\nPlanned routes, not observed trajectories or verified clearances')
        ax.set_aspect('equal',adjustable='datalim');ax.grid(alpha=.3);ax.legend(fontsize=8)
        fig.savefig(path,dpi=160)
    finally:plt.close(fig)
