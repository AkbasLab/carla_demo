"""Inference admission and attributable mission evidence, independent of model output."""
from collections import Counter


def admit_requests(agents,now,capacity):
    """Fair, bounded model service; inspect scheduling state only, never peer memory."""
    busy=sum(a.pending is not None or bool(a.worker and a.worker.busy) for a in agents)
    candidates=[]
    for a in agents:
        ready=(not a.authorized and not a.identity_fault and a.pending is None
               and not (a.worker and a.worker.busy) and now-a.last_request>=a.decision_interval
               and (not hasattr(a,'needs_decision') or a.needs_decision(now)))
        if ready:
            if a.request_waiting_since is None:a.request_waiting_since=now
            candidates.append(a)
        else:a.request_waiting_since=None
    ordered=sorted(candidates,key=lambda a:(a.last_request,a.agent_id))
    # Shared compute metadata only: never inspect task cost, telemetry or private beliefs.
    service=max((getattr(a,'inference_estimate',0.) for a in agents),default=0.)
    for rank,a in enumerate(ordered):a.inference_admission_delay_s=((busy+rank)//capacity)*service
    selected=ordered[:max(0,capacity-busy)]
    for a in selected:a.request(now)
    return [a.agent_id for a in selected]


def policy_evidence(agents,provider,all_guarded,error,mission_complete,duplicates,backend):
    context_activity={};useful={};llm_useful={};sources={};tools={};failures={};deadline_bids={};releases={}
    for a in agents:
        decisions=[e for e in a.events_policy if e['event']=='policy_decision_applied']
        context_activity[a.agent_id]=any(e.get('source')=='llm' and e.get('flight_phase')=='AIRBORNE' for e in decisions)
        accepted={e['request_id']:e for e in decisions if e['decision']['selected_tool'] in ('start_search','go_to_waypoint','act_as_relay','return_home')}
        all_observed=[e for e in a.events_policy if e['event']=='policy_progress_observed']
        observed=[e for e in all_observed
                  if e.get('request_id') in accepted and e.get('source')==accepted[e['request_id']].get('source')
                  and accepted[e['request_id']].get('flight_phase')=='AIRBORNE']
        useful[a.agent_id]=len({e['request_id'] for e in observed if e.get('request_id')})
        llm_useful[a.agent_id]=len({e['request_id'] for e in observed if e.get('source')=='llm' and e.get('request_id')})
        sources[a.agent_id]=dict(Counter(e.get('source','unknown') for e in all_observed))
        tools[a.agent_id]=dict(Counter(e['decision']['selected_tool'] for e in decisions))
        failures[a.agent_id]=dict(Counter(e['reason_code'] for e in a.events_policy if e['event']=='policy_error'))
        deadline_bids[a.agent_id]=sum(e['event']=='deadline_bid_submitted' for e in a.events_policy)
        releases[a.agent_id]=sum(e['event']=='blocked_task_released' for e in a.events_policy)
    integrated=provider=='ollama' and all(context_activity.values()) and all_guarded and error is None
    useful_observed=integrated and all(count>0 for count in llm_useful.values())
    return dict(llm_integration_observed=integrated,llm_exit_criterion_observed=useful_observed,
        live_exit_criterion_observed=useful_observed and backend=='airsim',
        cooperative_mission_success=useful_observed and mission_complete and duplicates==0,
        productive_decisions_by_agent=useful,llm_productive_decisions_by_agent=llm_useful,
        observed_progress_sources_by_agent=sources,policy_tools_by_agent=tools,policy_errors_by_agent=failures,
        deadline_bids_by_agent=deadline_bids,blocked_task_releases_by_agent=releases)
