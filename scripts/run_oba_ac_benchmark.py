"""Experiments A/C: reproducible geometric OBA proxy, no simulator needed."""
import argparse,csv,json,random,time,statistics,math
from pathlib import Path
BOX=(35.,65.,25.,55.)
def hit(a,b,box,margin=3.):
 x0,y0=a[:2];x1,y1=b[:2];dx=x1-x0;dy=y1-y0
 xmin,xmax,ymin,ymax=box;xmin-=margin;xmax+=margin;ymin-=margin;ymax+=margin
 lo,hi=0.,1.
 for p,q in ((-dx,x0-xmin),(dx,xmax-x0),(-dy,y0-ymin),(dy,ymax-y0)):
  if p==0:
   if q<0:return False
  else:
   r=q/p
   if p<0:lo=max(lo,r)
   else:hi=min(hi,r)
   if lo>hi:return False
 return True
def check(start,target,boxes,ceiling=30.,margin=3.):
 reasons=[]
 if not 0<=-target[2]<=ceiling:reasons.append("altitude")
 if any(hit(start,target,b,margin) for b in boxes):reasons.append("obstacle")
 return ("reject" if reasons else "accept"),reasons
def pct(v,p):
 s=sorted(v);i=(len(s)-1)*p/100;lo=math.floor(i);hi=math.ceil(i)
 return s[lo]+(s[hi]-s[lo])*(i-lo)
def summary(v):
 return dict(n=len(v),mean_us=statistics.mean(v),median_us=pct(v,50),p95_us=pct(v,95),p99_us=pct(v,99),max_us=max(v))
def run(args):
 if args.repeats<1 or args.random_cases<0 or args.max_obstacles<1:raise ValueError("Invalid trial count")
 out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
 rng=random.Random(args.seed)
 cases=[("obstacle",(0.,0.,-10.),(100.,80.,-10.)),("altitude",(0.,0.,-10.),(10.,10.,-55.)),("safe",(0.,0.,-10.),(10.,10.,-10.)),("both",(0.,0.,-10.),(100.,80.,-55.))]
 for i in range(args.random_cases):
  cases.append((f"random_{i:05d}",(rng.uniform(-20,20),rng.uniform(-20,20),-10.),(rng.uniform(-20,110),rng.uniform(-20,110),-rng.uniform(1,55))))
 rows=[]
 for name,start,target in cases:
  unsafe=not (0<=-target[2]<=args.ceiling) or hit(start,target,BOX,args.margin)
  t=time.perf_counter_ns();decision,reasons=check(start,target,[BOX],args.ceiling,args.margin);elapsed=(time.perf_counter_ns()-t)/1000
  rows.append(dict(case_id=name,start=str(start),target=str(target),unsafe=unsafe,decision=decision,reasons=";".join(reasons),latency_us=elapsed))
 n=len(rows);u=sum(r["unsafe"] for r in rows);s=n-u
 rejected=sum(r["decision"]=="reject" for r in rows)
 blocked=sum(r["unsafe"] and r["decision"]=="reject" for r in rows)
 false=sum(not r["unsafe"] and r["decision"]=="reject" for r in rows)
 effectiveness=dict(cases=n,unsafe=u,safe=s,unguarded_unsafe_proposal_rate=u/n,guarded_unsafe_dispatch_rate=(u-blocked)/n,intervention_rate=rejected/n,unsafe_prevention_rate=blocked/u if u else None,false_rejection_rate=false/s if s else None)
 scaling=[]
 for k in sorted(set([1,2,4,8,16,args.max_obstacles])):
  if k>args.max_obstacles:continue
  boxes=[(35+i*80.,65+i*80.,25.,55.) for i in range(k)]
  durations=[]
  for _ in range(args.repeats):
   t=time.perf_counter_ns();check((0.,-30.,-10.),(10.,-20.,-10.),boxes,args.ceiling,args.margin);durations.append((time.perf_counter_ns()-t)/1000)
  scaling.append(dict(obstacles=k,**summary(durations)))
 for filename,data in (("cases.csv",rows),("latency_scaling.csv",scaling)):
  with (out/filename).open("w",newline="",encoding="utf8") as f:
   w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
 report=dict(seed=args.seed,random_cases=args.random_cases,repeats=args.repeats,ceiling=args.ceiling,margin=args.margin,effectiveness=effectiveness,latency_scaling=scaling,limitations=["Geometric candidate-segment checks, not executed trajectories or physical collisions","No LLM, simulator RPC or telemetry overhead","Reject-only guardian, no rerouting","Timing depends on host hardware and Python version"])
 (out/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
 print(json.dumps(report,indent=2))
if __name__=="__main__":
 p=argparse.ArgumentParser()
 p.add_argument("--output-dir",default="results/oba_ac")
 p.add_argument("--seed",type=int,default=42)
 p.add_argument("--random-cases",type=int,default=200)
 p.add_argument("--repeats",type=int,default=1000)
 p.add_argument("--max-obstacles",type=int,default=16)
 p.add_argument("--ceiling",type=float,default=30.)
 p.add_argument("--margin",type=float,default=3.)
 run(p.parse_args())
