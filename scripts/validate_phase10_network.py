"""Validate the abstract network and write measured Phase 10 evidence to docs."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agentic_uav.comm.degraded import NetworkConfig, DegradedMessageBus, preset
from agentic_uav.comm.protocol import AgentMessage, MessageType


def packet(sender,sequence,now,recipients,ttl=10):
    return AgentMessage(f'{sender}:{sequence}',MessageType.HEARTBEAT,sender,recipients,
                        'network_validation',now,sequence,ttl,{'alive':True})


def sample(config,seed,count):
    now=[0.]
    bus=DegradedMessageBus(['sender','receiver'],lambda:now[0],config,seed)
    for i in range(1,count+1):bus.endpoint('sender').send(packet('sender',i,0,['receiver']))
    now[0]=1.;bus.endpoint('receiver').receive_available()
    logs=bus.logs()
    digest=hashlib.sha256(json.dumps(logs,sort_keys=True).encode()).hexdigest()
    delays=[r['latency_sample_s']*1000 for r in logs]
    losses=sum(r['drop_reason']=='independent_loss' for r in logs)
    return dict(offered_packets=count,independent_losses=losses,loss_fraction=losses/count,
                sampled_latency_mean_ms=statistics.mean(delays),sampled_latency_variance_ms2=statistics.pvariance(delays),
                sampled_latency_min_ms=min(delays),sampled_latency_max_ms=max(delays),
                maximum_uniform_cdf_error=max(abs(sum(x<=config.latency_ms_mean-config.latency_ms_jitter+
                    2*config.latency_ms_jitter*k/10 for x in delays)/count-k/10) for k in range(11)),
                outcomes=dict(Counter(r['status'] for r in logs)),trace_sha256=digest)


def partition_check():
    ids=['Drone1','Drone2','Drone3','Drone4','BaseStation'];now=[0.]
    config=NetworkConfig(latency_ms_mean=0,latency_ms_jitter=0,
        partitions=[dict(start_s=5,end_s=12,groups=[['Drone1','Drone2'],['Drone3','Drone4','BaseStation']])])
    bus=DegradedMessageBus(ids,lambda:now[0],config)
    observations=[]
    for step,t in enumerate([4.,5.,11.9,12.],1):
        now[0]=t
        for sender in ids:bus.endpoint(sender).send(packet(sender,step,t,[p for p in ids if p!=sender]))
        for recipient in ids:bus.endpoint(recipient).receive_available()
        logs=bus.logs()[-20:]
        passed=all((r['status']=='dropped') == (5<=t<12 and ((r['sender_id'] in ids[:2]) != (r['recipient_id'] in ids[:2]))) for r in logs)
        observations.append(dict(time_s=t,delivered=sum(r['status']=='delivered' for r in logs),
                                 partition_drops=sum(r['drop_reason']=='partition' for r in logs),passed=passed))
    return dict(passed=all(r['passed'] for r in observations),groups=config.partitions[0]['groups'],observations=observations)


def expiry_check():
    now=[0.];bus=DegradedMessageBus(['sender','receiver'],lambda:now[0],NetworkConfig(latency_ms_mean=500,latency_ms_jitter=0))
    bus.endpoint('sender').send(packet('sender',1,0,['receiver'],ttl=.5))
    bus.endpoint('sender').send(packet('sender',2,0,['receiver'],ttl=2))
    now[0]=.49;early=bus.endpoint('receiver').receive_available()
    now[0]=.5;received=bus.endpoint('receiver').receive_available()
    return dict(passed=not early and [m.sequence_number for m in received]==[2] and bus.logs()[0]['expired'],
                rejected_at_exact_ttl=True,received_sequences=[m.sequence_number for m in received])


def validate(seed=42,count=10000):
    measurements=[]
    for name in ['nominal','moderate','severe']:
        config=preset(name)
        # Isolate raw network distribution from queuing, range and partitions.
        config.message_rate_limit=None;config.bandwidth_bytes_per_second=None
        first=sample(config,seed,count);repeat=sample(config,seed,count);other=sample(config,seed+1,count)
        jitter=config.latency_ms_jitter;expected_var=jitter*jitter/3
        checks=dict(loss_within_two_percentage_points=abs(first['loss_fraction']-config.packet_loss_probability)<=.02,
            latency_mean_within_two_ms=abs(first['sampled_latency_mean_ms']-config.latency_ms_mean)<=2,
            uniform_cdf_error_at_most_002=first['maximum_uniform_cdf_error']<=.02,
            latency_within_configured_support=(first['sampled_latency_min_ms']>=config.latency_ms_mean-jitter and first['sampled_latency_max_ms']<=config.latency_ms_mean+jitter),
            variance_within_five_percent=abs(first['sampled_latency_variance_ms2']-expected_var)<=.05*expected_var,
            identical_seed_identical_trace=first['trace_sha256']==repeat['trace_sha256'],
            different_seed_different_trace=first['trace_sha256']!=other['trace_sha256'])
        measurements.append(dict(condition=name,configuration=asdict(config),measured=first,checks=checks,passed=all(checks.values())))
    partition=partition_check();expiration=expiry_check()
    return dict(seed=seed,packets_per_condition=count,statistical_conditions=measurements,
                base_station_partition=partition,expiration=expiration,
                passed=all(r['passed'] for r in measurements) and partition['passed'] and expiration['passed'])


def report(data):
    rows=[]
    for r in data['statistical_conditions']:
        m=r['measured'];c=r['configuration']
        rows.append(f"| {r['condition']} | {100*c['packet_loss_probability']:.0f}% | {100*m['loss_fraction']:.3f}% | {c['latency_ms_mean']:.0f} | {m['sampled_latency_mean_ms']:.3f} | {'PASS' if r['passed'] else 'FAIL'} |")
    return '''# Phase 10 validation and completion report

## Scope and assessment

The initial degraded-communications simulator is implemented for mock application-level messages. All checks in the accompanying `phase10_network_validation.json` passed: **%s**. This establishes reproducible controlled faults, not resilient mission completion or calibrated RF behavior.

## Requirement coverage

| Requirement | Evidence / implementation |
|---|---|
| 10.1 Configurable model | All six initial settings: mean latency, jitter, independent loss, rate, bandwidth and hard distance cutoff. Timed partitions also implemented. |
| 10.2 Four conditions | Nominal, moderate, severe and partitioned presets; matched-seed mission results committed under `results/phase10/multiseed_1_30`. Base-station link isolation checked separately below. |
| 10.3 Reproducibility | Same seed and identical offered trace produce identical complete network-log hashes. Different seeds produce different traces. Fixed mission/target locations and explicitly scheduled failures are deterministic; target randomization is unnecessary for the current fixed scenario. |
| 10.4 Expiration | Creation-time TTL is enforced at receipt, including exact expiration. Phase 10 endpoints use 1.5 s heartbeat, 2 s intent, 60 s target, and mission-update lifetime beyond the experiment horizon. |
| 10.5 Local health estimates | Agents observe heartbeat arrival rate/age, missing sequences and piggyback ACK counts/RTT through their endpoint; network settings remain infrastructure-only. The recovery policy mainly uses heartbeat age. |
| 10.6 Statistical checks | Measured loss, uniform latency support/CDF/mean/variance, same-seed hashes, selective partitions and expiration, plus the automated network tests. |

## Statistical network measurements

Seed **%s**, **%s offered recipient packets per condition**, plus an identical-seed replay and a different-seed comparison for each condition. Distribution checks deliberately disable rate/bandwidth limits to isolate raw loss and latency sampling. They do not substitute for queueing tests. Loss tolerance is ±2 percentage points, mean latency ±2 ms, uniform CDF error ≤0.02, variance within 5%% of the theoretical uniform variance, and exact support bounds.

| Condition | Configured loss | Measured loss | Configured mean (ms) | Measured mean (ms) | Checks |
|---|---:|---:|---:|---:|---|
%s

Raw latency is uniform over mean ± jitter. Actual application receipt includes polling, queueing and serialization, so it can exceed this interval. Full measured variances, CDF errors, counts and replay hashes are in the JSON evidence.

## Base-station partition and expiration

The focused test registers four drones plus `BaseStation`, with groups `[Drone1, Drone2]` and `[Drone3, Drone4, BaseStation]`. At 5.0 and 11.9 s, only the 12 directed cross-group copies are blocked; the 8 within-group copies arrive. At 4.0 and 12.0 s, all 20 directed copies arrive. This verifies both directions, unaffected links, base-station isolation from one group, and restoration at the interval boundary. This is a transport test, not a new five-agent mission controller.

The expiration test schedules 500 ms latency. A message with a 500 ms TTL is rejected at the exact deadline; one with a 2 s TTL arrives. No packet arrives before its scheduled time.

## Mission-level findings: seeds 1–30

All trials use the same four search tasks, no stopped agent and a 120 s maximum horizon. Task completion counts refer to mock work events; mission success additionally requires agreement across all active local task ledgers.

| Condition | Mission successes | Runs with all four tasks completed | Mean successful completion time |
|---|---:|---:|---:|
| Nominal | 30/30 | 30/30 | 18.1 s |
| Moderate | 10/30 | 27/30 | 55.38 s |
| Severe | 0/30 | 0/30 | Not observed |
| Partitioned | 0/30 | 0/30 | Not observed |

No duplicate completions were recorded. Incomplete trials are right-censored, not assigned a successful completion time. Moderate results expose completion-state reconciliation problems; severe results expose role/health instability and queue-driven expiration; partitioned results expose failure to restore full-mission execution after connectivity returns. These are coordination limitations, not evidence that message degradation failed to occur. Intervals in the multi-seed comparison apply to network randomness for this fixed mock mission, not real flight or other mission geometries.

## Reproduce

```bash
python scripts/validate_phase10_network.py --seed 42 --messages 10000
python -m unittest discover -s tests -p 'test_phase10*.py' -v
python scripts/run_phase10_sweep.py --seeds $(seq 1 30) --output-dir results/phase10/new_sweep
```

The validator regenerates this Markdown and `docs/phase10_network_validation.json`; a failed validation exits nonzero. Use a new sweep directory to preserve earlier results.

## Boundaries and deferred work

Burst loss, interference zones and asymmetric links are explicitly later extensions and remain deferred. No live CARLA–AirSim integration, RF calibration or relay-throughput improvement is claimed. Queueing is unbounded FIFO pacing; radio contention and propagation are not modeled. Range is a hard cutoff sampled by infrastructure, not sensed by agents. ACK RTT includes peer scheduling; sequence gaps can represent reordering or selective addressing rather than proven packet loss. The current all-peer broadcast mission makes sequence gaps interpretable. Common seeds align random draws for matching sender/sequence/recipient keys, not different packets generated by diverging architectures.

**Exit criterion:** satisfied for the initial mock scope: the same mission can be replayed under all four conditions with reproducible message delivery. Successful recovery across those conditions remains future coordination work.
''' % ('PASS' if data['passed'] else 'FAIL',data['seed'],data['packets_per_condition'],'\n'.join(rows))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',type=int,default=42);p.add_argument('--messages',type=int,default=10000)
    p.add_argument('--output-dir',default='docs');a=p.parse_args()
    if a.messages<10000:p.error('Statistical validation requires at least 10000 messages per condition')
    data=validate(a.seed,a.messages);out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'phase10_network_validation.json').write_text(json.dumps(data,indent=2)+'\n')
    (out/'phase10_report.md').write_text(report(data))
    print(json.dumps(data,indent=2))
    if not data['passed']:raise SystemExit(1)

if __name__=='__main__':main()
