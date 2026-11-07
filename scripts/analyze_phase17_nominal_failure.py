"""Read-only trace of the selected Phase 17 nominal policy-silence failure."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def analyze(folder, output):
    folder=Path(folder);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    def read(name):return json.loads((folder/name).read_text())
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines()]
    flight=read('run/flight_trace.json');protocol=read('run/protocol_events.json')
    fault=next(e for e in events if e['event_type']=='FAULT_INJECTED');onset=fault['simulation_time_s'];failed=fault['agent_id']
    survivor=next(r['agent_id'] for r in flight if r['agent_id']!=failed)
    after=[r for r in flight if r['agent_id']==survivor and r['time_s']>=onset]
    milestones=[]
    for state in ('SUSPECTED','UNREACHABLE'):
        row=next((r for r in after if r['peer_health'].get(failed)==state),None)
        if row:milestones.append(dict(time_s=row['time_s'],stage=state,agent_id=survivor))
    relevant=[e for e in protocol if e['time_s']>=onset and e['event'] in ('lease_expired','task_announced','bid_computed','claim_sent','execution_started')]
    rejected=[e for e in events if e['event_type']=='GUARDIAN_INTERVENED' and e['simulation_time_s']>=onset]
    reasons=Counter(reason for e in rejected for reason in e['data']['audit']['reasons'])
    row=dict(experiment_id=folder.name,fault_s=onset,failed_agent=failed,surviving_agent=survivor,
        fault_position=next(r['position'] for r in flight if r['agent_id']==failed and r['time_s']>=onset),
        health_milestones=milestones,protocol_after_fault=relevant,
        first_post_fault_guardian_intervention=rejected[0] if rejected else None,
        post_fault_guardian_reasons=dict(reasons),waypoint_arrivals=len(read('run/waypoint_arrivals.json')),
        summary=read('run/summary.json'),
        artifact_sha256={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in
            ('manifest.json','events.jsonl','run/flight_trace.json','run/protocol_events.json','run/summary.json')})
    (output/'nominal_failure_diagnosis.json').write_text(json.dumps(row,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,1,figsize=(10,8),sharex=True,layout='constrained')
    for aid in sorted({r['agent_id'] for r in flight}):
        rows=[r for r in flight if r['agent_id']==aid]
        axes[0].plot([r['time_s'] for r in rows],[r['position'][0] for r in rows],label=aid)
    axes[0].set(ylabel='Observed X (m)',title='Motion stops after the policy-silence fault');axes[0].legend()
    health={'HEALTHY':0,'SUSPECTED':1,'UNREACHABLE':2}
    rows=[r for r in flight if r['agent_id']==survivor]
    axes[1].step([r['time_s'] for r in rows],[health.get(r['peer_health'].get(failed),0) for r in rows],where='post')
    axes[1].set(yticks=[0,1,2],yticklabels=['Healthy','Suspected','Unreachable'],ylabel='Local peer health')
    stale=[e['simulation_time_s'] for e in rejected if 'stale_or_future_peer_belief' in e['data']['audit']['reasons']]
    axes[2].step(stale,range(1,len(stale)+1),where='post',label='Stale-peer guardian interventions')
    for e in relevant:
        if e['event']=='lease_expired':axes[2].axvline(e['time_s'],color='grey',ls=':',alpha=.8)
    axes[2].set(xlabel='Mission time (s)',ylabel='Cumulative count');axes[2].legend(loc='upper left')
    for ax in axes:
        ax.axvline(onset,color='red',ls='--',label='Fault');ax.grid(alpha=.2)
    fig.suptitle('Nominal communication does not prevent stale-peer recovery deadlock\nD, two drones, seed 41; recorded pilot, V2 disabled')
    fig.savefig(output/'nominal_failure_diagnosis.png',dpi=140);plt.close(fig)
    return dict(fault_s=onset,health=milestones,guardian_reasons=dict(reasons),post_fault_protocol=relevant)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True);parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();print(json.dumps(analyze(args.run_dir,args.output_dir),indent=2))
