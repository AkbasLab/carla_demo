"""Four deterministic mock agents: private beliefs change only on inbox receipt."""
import json
from pathlib import Path
from agentic_uav.comm.protocol import MessageType, PerfectMessageBus, new_message


class ProtocolAgent:
    def __init__(self, agent_id, peers, endpoint):
        self.agent_id, self.peers, self.endpoint = agent_id, peers, endpoint
        self.sequence = 0
        self.position = [0., 0., -5.]
        self.team_beliefs = {}
        self.received_types = set()
        self.action = "hold_for_peer_status"

    def send(self, kind, payload, now):
        self.sequence += 1
        self.endpoint.send(new_message(kind, self.agent_id, self.peers,
                           'phase7-demo', now, self.sequence, payload))

    def receive(self):
        for msg in self.endpoint.receive_available():
            self.received_types.add(msg.message_type.value)
            if msg.mission_id != 'phase7-demo':
                continue
            if msg.message_type in (MessageType.HEARTBEAT, MessageType.STATUS_UPDATE):
                belief = self.team_beliefs.setdefault(msg.sender_id, {})
                belief.update(msg.payload)
                belief['last_received_creation_time'] = msg.timestamp
                if msg.message_type == MessageType.STATUS_UPDATE and 'in_air' in msg.payload:
                    self.action = ('continue_mock_flight' if all(self.team_beliefs.get(peer, {}).get('in_air') for peer in self.peers)
                                   else 'hold_for_peer_status')
                    self.endpoint.mark_influenced(msg.message_id)
            # Other types are protocol probes, not implemented task-allocation decisions.


def run_protocol_demo(ticks=20, dt=.1, output_dir='results/phase7/protocol'):
    now = [0.]
    ids = [f'Drone{i}' for i in range(1,5)]
    bus = PerfectMessageBus(ids, lambda: now[0])
    agents = [ProtocolAgent(agent, [peer for peer in ids if peer != agent], bus.endpoint(agent)) for agent in ids]
    trace = []
    # Exercise all 13 envelopes under reliable communication; allocation semantics are Phase 8.
    for kind in MessageType:
        agents[0].send(kind, {'protocol_probe': True}, now[0])
    for tick in range(ticks):
        now[0] = tick*dt
        for index, agent in enumerate(agents):
            # Deterministic local kinematics, not AirSim or a physical flight model.
            if agent.action == "continue_mock_flight":
                agent.position[0] += dt*(index+1)
            agent.send(MessageType.HEARTBEAT, {'alive': True}, now[0])
            agent.send(MessageType.STATUS_UPDATE, {'position': list(agent.position), 'role': 'searcher', 'in_air': True}, now[0])
        for agent in agents:
            agent.receive()
            trace.append(dict(time_s=now[0], agent_id=agent.agent_id,
                              own_position=list(agent.position), action=agent.action, team_beliefs=json.loads(json.dumps(agent.team_beliefs))))
    logs = bus.logs()
    result = dict(mode='perfect_communication_mock_protocol', agents=4, ticks=ticks,
        message_types=[kind.value for kind in MessageType],
        message_instances=len(set(r['message_id'] for r in logs)),
        recipient_deliveries=len(logs), delivered=sum(r['status']=='delivered' for r in logs),
        all_peer_beliefs_present=all(set(a.team_beliefs)==set(a.peers) for a in agents),
        limitations=['Mock kinematics only; live four-drone flight remains unvalidated',
                     'All 13 envelopes exercised; task auctions, leases, role negotiation are not implemented here',
                     'Legacy RF bus and Experiment D are separate; no automatic protocol migration',
                     'Endpoint isolation is an API design convention, not an adversarial process sandbox'])
    out = Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    (out/'messages.json').write_text(json.dumps(logs,indent=2)+'\n')
    (out/'beliefs.json').write_text(json.dumps(trace,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result
