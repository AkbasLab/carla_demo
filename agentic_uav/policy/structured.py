"""Phase 12 bounded decision language and pinned shared Ollama provider."""
import copy
import hashlib
import json
import math
import queue
import re
import threading
import time
import urllib.request


class PolicyError(ValueError):
    def __init__(self,reason,details=None):
        super().__init__(reason)
        self.details=details

class ModelIdentityError(PolicyError):pass


# Parameters are deliberately small. Tools resolve geometry/costs from local state.
TOOLS={
 'accept_task':{'task_id':'str','task_version':'int'},
 'decline_task':{'task_id':'str','task_version':'int','reason_code':'reason'},
 'compute_task_cost':{'task_id':'str'},
 'announce_task':{'task_id':'str'},
 'send_bid':{'task_id':'str','task_version':'int'},
 'claim_task':{'task_id':'str','task_version':'int'},
 'release_task':{'task_id':'str','task_version':'int','reason_code':'reason'},
 'change_role':{'new_role':'role','reason_code':'reason'},
 'request_help':{'reason_code':'reason'},
 'report_target':{'observation_id':'str'},
 'start_search':{'task_id':'str','task_version':'int'},
 'go_to_waypoint':{'task_id':'str','task_version':'int','waypoint_index':'int','speed_mps':'positive'},
 'act_as_relay':{},'return_home':{},'hold':{'duration_s':'positive'},
}


def decision_schema(context=None):
    types={'str':{'type':'string','minLength':1,'maxLength':100},
           'int':{'type':'integer','minimum':0},
           'positive':{'type':'number','exclusiveMinimum':0},
           'reason':{'type':'string','pattern':'^[A-Z0-9_]{1,48}$'},
           'role':{'type':'string','enum':['SCOUT','RELAY','RESERVE']}}
    base=dict(type='object',additionalProperties=False,required=['situation_assessment','selected_tool','parameters','outgoing_messages','confidence'])
    base['properties']={
        'situation_assessment':dict(type='object',additionalProperties=False,
            required=['mission_progress','communication_status','current_risk'],properties={
                'mission_progress':dict(type='string',enum=['none','partial','complete']),
                'communication_status':dict(type='string',enum=['nominal','degraded','lost','unknown']),
                'current_risk':dict(type='string',enum=['low','medium','high','unknown'])}),
        'selected_tool':dict(type='string',enum=list(TOOLS)),
        'parameters':dict(type='object'),
        'outgoing_messages':dict(type='array',maxItems=1,items=dict(type='object',additionalProperties=False,
            required=['message_type','recipients','payload'],properties=dict(message_type=dict(type='string',enum=['ROLE_CHANGE','HELP_REQUEST']),
                recipients=dict(type='array',minItems=1,uniqueItems=True,items=dict(type='string')),payload=dict(type='object')))),
        'confidence':dict(type='number',minimum=0,maximum=1)}
    # Some schema-to-grammar converters select a oneOf branch without merging
    # its siblings. Each branch must therefore be a complete decision schema.
    offered=context.get('available_tools') if context else None
    candidates=context.get('tool_candidates',{}) if context else {}
    if offered is not None:
        if not isinstance(offered,dict) or not offered or any(tool not in TOOLS for tool in offered):raise PolicyError('invalid_context_tools')
        base['properties']['selected_tool']['enum']=list(offered)
    branches=[]
    for tool,params in TOOLS.items():
        if offered is not None and tool not in offered:continue
        branch=copy.deepcopy(base)
        branch['properties']['selected_tool']={'const':tool}
        branch['properties']['parameters']=dict(type='object',additionalProperties=False,
            required=list(params),properties={key:copy.deepcopy(types[kind]) for key,kind in params.items()})
        examples=candidates.get(tool,[])
        for name in ('task_id','task_version','waypoint_index','observation_id','new_role'):
            values=[call[name] for call in examples if name in call]
            if values and name in branch['properties']['parameters']['properties']:
                branch['properties']['parameters']['properties'][name]['enum']=sorted(set(values))
        if tool=='hold' and context:
            branch['properties']['parameters']['properties']['duration_s']['maximum']=context.get('policy_limits',{}).get('max_hold_seconds',2.)
        branches.append(branch)
    base['oneOf']=branches
    return base


def decision_example(selected_tool='hold',parameters=None):
    return dict(situation_assessment=dict(mission_progress='partial',communication_status='nominal',current_risk='low'),
        selected_tool=selected_tool,parameters=parameters if parameters is not None else dict(duration_s=1.),outgoing_messages=[],confidence=.8)


def validate_decision(raw,peers):
    if not isinstance(raw,str) or len(raw.encode())>65536:raise PolicyError('response_size_or_type')
    def reject_constant(value):raise PolicyError('nonfinite_json')
    def unique_keys(items):
        result={}
        for k,v in items:
            if k in result:raise PolicyError('duplicate_json_key')
            result[k]=v
        return result
    try:d=json.loads(raw,parse_constant=reject_constant,object_pairs_hook=unique_keys)
    except (ValueError,TypeError) as e:raise PolicyError('invalid_json') from e
    required={'situation_assessment','selected_tool','parameters','outgoing_messages','confidence'}
    if not isinstance(d,dict):raise PolicyError('decision_fields',dict(expected_fields=sorted(required),received_type=type(d).__name__))
    if set(d)!=required:raise PolicyError('decision_fields',dict(missing_fields=sorted(required-set(d)),unexpected_fields=sorted(set(d)-required),expected_fields=sorted(required)))
    assessment=d['situation_assessment']
    allowed=dict(mission_progress={'none','partial','complete'},communication_status={'nominal','degraded','lost','unknown'},current_risk={'low','medium','high','unknown'})
    if not isinstance(assessment,dict) or set(assessment)!=set(allowed):raise PolicyError('assessment_fields')
    if any(not isinstance(assessment[k],str) or assessment[k] not in allowed[k] for k in allowed):raise PolicyError('assessment_values')
    tool=d['selected_tool']
    if not isinstance(tool,str) or tool not in TOOLS:raise PolicyError('invalid_tool')
    params=d['parameters']
    if not isinstance(params,dict) or set(params)!=set(TOOLS[tool]):raise PolicyError('tool_parameters')
    for key,kind in TOOLS[tool].items():
        v=params[key]
        if kind=='int':ok=type(v) is int and v>=0
        elif kind=='positive':ok=type(v) in (int,float) and math.isfinite(v) and v>0
        elif kind=='role':ok=isinstance(v,str) and v in ('SCOUT','RELAY','RESERVE')
        elif kind=='reason':ok=isinstance(v,str) and re.fullmatch('[A-Z0-9_]{1,48}',v) is not None
        else:ok=isinstance(v,str) and 0<len(v)<=100
        if not ok:raise PolicyError('invalid_parameter:'+key)
    if type(d['confidence']) not in (float,int) or not math.isfinite(d['confidence']) or not 0<=d['confidence']<=1:raise PolicyError('invalid_confidence')
    outgoing=d['outgoing_messages']
    if not isinstance(outgoing,list) or len(outgoing)>1:raise PolicyError('outgoing_messages')
    if outgoing:
        m=outgoing[0]
        if not isinstance(m,dict) or set(m)!={'message_type','recipients','payload'}:raise PolicyError('outgoing_fields')
        recipients=m['recipients']
        if not isinstance(recipients,list) or not recipients or any(not isinstance(r,str) or r not in peers for r in recipients) or len(set(recipients))!=len(recipients):raise PolicyError('invalid_recipient')
        expected_type={'change_role':'ROLE_CHANGE','request_help':'HELP_REQUEST'}.get(tool)
        payload=({'role':params['new_role'],'reason_code':params['reason_code']} if tool=='change_role' else
                 {'reason_code':params['reason_code']} if tool=='request_help' else None)
        if m['message_type']!=expected_type or m['payload']!=payload:raise PolicyError('message_tool_mismatch')
    return d


class OllamaProvider:
    """One stateless shared server; every request supplies one isolated agent context."""
    def __init__(self,model,digest,url='http://localhost:11434',timeout=15.,seed=42):
        if not model or model.endswith(':latest') or ':' not in model:raise ModelIdentityError('Use an explicit non-latest model tag')
        if not re.fullmatch(r'(sha256:)?[0-9a-f]{64}',digest or ''):raise ModelIdentityError('Expected exact 64-hex SHA256 model digest')
        self.model=model;self.digest=digest.removeprefix('sha256:');self.url=url.rstrip('/');self.timeout=timeout
        self.options=dict(temperature=0,seed=seed,num_predict=512,num_ctx=8192)
        self.server_version=None

    def _http(self,path,data=None):
        request=urllib.request.Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=self.timeout) as response:
            content=response.read(1048577)
            if len(content)>1048576:raise PolicyError('provider_response_too_large')
            return json.loads(content)

    def verify(self):
        if self.server_version is None:self.server_version=self._http('/api/version').get('version','unknown')
        models=self._http('/api/tags').get('models',[])
        found=next((m for m in models if m.get('name')==self.model or m.get('model')==self.model),None)
        if found is None or found.get('digest','').removeprefix('sha256:')!=self.digest:raise ModelIdentityError('model_digest_mismatch')
        return dict(provider='ollama',model=self.model,digest=self.digest,options=copy.deepcopy(self.options),
                    server=self.url,server_version=self.server_version,details=found.get('details',{}))

    def warmup(self):
        self.verify();started=time.monotonic()
        self._http('/api/generate',dict(model=self.model,prompt='',stream=False,keep_alive='10m',options=self.options))
        self.verify()
        return dict(performed=True,latency_s=time.monotonic()-started)

    def request_spec(self,prompt):
        context=json.loads(prompt)
        example=context.get('decision_format',{}).get('example',decision_example())
        return dict(model=self.model,stream=False,format=decision_schema(context),
            messages=[dict(role='system',content='You are one UAV high-level agent. Use ONLY the listed structured tools. Do not emit code or private chain of thought. Use short reason codes. Deterministic tools calculate geometry, costs and safety. Send a bid only for an open bidding task while idle; start_search only for your own executable task. Use hold when genuinely waiting or when motion is unsafe. When your owned task is executable, prioritize starting its search or evaluating its cost; repeating hold is not task progress. Do not request motion merely to calculate a cost. Respect ownership and guardian constraints. Your response must contain ALL FIVE top-level fields: situation_assessment, selected_tool, parameters, outgoing_messages, confidence. Never return only selected_tool and parameters. outgoing_messages may be an empty array. Complete shape example (choose your own valid tool and values): '+json.dumps(example)),
                      dict(role='user',content=prompt)],options=copy.deepcopy(self.options))

    def generate(self,prompt):
        # Check both sides of inference. Never silently accept a tag replacement.
        self.verify()
        response=self._http('/api/chat',self.request_spec(prompt))
        self.verify()
        raw=response['message']['content']
        if not isinstance(raw,str) or len(raw.encode())>65536:raise PolicyError('response_size_or_type')
        return raw


class AsyncWorker:
    """At most one bounded RPC per agent; outer control loop owns the deadline."""
    def __init__(self,provider):
        self.provider=provider;self.result=queue.Queue(maxsize=1);self.thread=None;self.started=None;self.token=None

    @property
    def busy(self):return self.thread is not None

    def submit(self,token,prompt):
        if self.busy:return False
        self.token=token;self.started=time.monotonic()
        def work():
            try:r=dict(token=token,raw=self.provider.generate(prompt))
            except Exception as e:r=dict(token=token,error_type=type(e).__name__)
            r['latency_s']=time.monotonic()-self.started
            self.result.put_nowait(r)
        self.thread=threading.Thread(target=work,daemon=True);self.thread.start();return True

    def poll(self):
        try:result=self.result.get_nowait()
        except queue.Empty:return None
        self.thread=None;self.started=None;self.token=None
        return result


class ReplayProvider:
    """Deterministic fixtures, explicitly NOT LLM inference."""
    def verify(self):return dict(provider='replay',model=None,digest=None,options={},llm_inference=False)

    def generate(self,prompt):
        c=json.loads(prompt);active=c['current_task'];role=c['current_role']
        params={};tool='hold'
        if active and active['executable']:
            tool='start_search';params=dict(task_id=active['task_id'],task_version=active['version'])
        elif active:tool='compute_task_cost';params=dict(task_id=active['task_id'])
        elif role=='RELAY':tool='act_as_relay'
        elif role=='RESERVE':params=dict(duration_s=1.)
        else:
            available=next((t for t in c['tasks'] if t['status']=='bidding' and t['own_bid'] is False),None)
            if available:tool='send_bid';params=dict(task_id=available['task_id'],task_version=available['version'])
            else:params=dict(duration_s=1.)
        d=dict(situation_assessment=dict(mission_progress='partial',communication_status='nominal',current_risk='low'),
            selected_tool=tool,parameters=params,outgoing_messages=[],confidence=1.)
        return json.dumps(d)
