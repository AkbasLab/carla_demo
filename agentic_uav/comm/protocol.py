"""Phase 7 message envelope and perfect-communication inbox transport.

Transport is simulator infrastructure; give agents an AgentEndpoint, not this bus.
"""
from dataclasses import dataclass, asdict
from enum import Enum
import copy
import json
import math
import uuid


class MessageType(str, Enum):
    HEARTBEAT = 'HEARTBEAT'
    STATUS_UPDATE = 'STATUS_UPDATE'
    TASK_ANNOUNCEMENT = 'TASK_ANNOUNCEMENT'
    TASK_BID = 'TASK_BID'
    TASK_AWARD = 'TASK_AWARD'
    TASK_ACCEPT = 'TASK_ACCEPT'
    TASK_RELEASE = 'TASK_RELEASE'
    TASK_COMPLETE = 'TASK_COMPLETE'
    INTENT_UPDATE = 'INTENT_UPDATE'
    TARGET_FOUND = 'TARGET_FOUND'
    HELP_REQUEST = 'HELP_REQUEST'
    ROLE_CHANGE = 'ROLE_CHANGE'
    MISSION_UPDATE = 'MISSION_UPDATE'


@dataclass
class AgentMessage:
    message_id: str
    message_type: MessageType
    sender_id: str
    recipient_ids: list
    mission_id: str
    timestamp: float
    sequence_number: int
    time_to_live_s: float
    payload: dict
    confidence: float | None = None

    def __post_init__(self):
        self.message_type = MessageType(self.message_type)
        if any(not isinstance(v, str) or not v for v in (self.message_id, self.sender_id, self.mission_id)):
            raise ValueError('Message, sender, and mission IDs must be nonempty strings')
        if not isinstance(self.recipient_ids, list) or not self.recipient_ids or any(not isinstance(r, str) or not r for r in self.recipient_ids) or len(set(self.recipient_ids)) != len(self.recipient_ids):
            raise ValueError('Recipients must be an explicit nonempty unique list')
        if isinstance(self.sequence_number, bool) or not isinstance(self.sequence_number, int) or self.sequence_number < 1:
            raise ValueError('Sequence number must be a positive integer')
        for value in (self.timestamp, self.time_to_live_s):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Times must be finite numeric values')
        if self.timestamp < 0 or self.time_to_live_s <= 0:
            raise ValueError('Invalid timestamp or TTL')
        if self.confidence is not None and (isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1):
            raise ValueError('Confidence must be null or in [0,1]')
        if not isinstance(self.payload, dict):
            raise ValueError('Payload must be a dictionary')
        self.to_json()  # Strict finite JSON; no Python objects or NaN in payload.

    def to_json(self):
        return json.dumps(asdict(self), allow_nan=False, sort_keys=True)

    @classmethod
    def from_json(cls, text):
        return cls(**json.loads(text))


class AgentEndpoint:
    """Agent-local API; no queue or other agents' memories are exposed."""
    def __init__(self, sender, receive, mark):
        self._sender, self._receive, self._mark = sender, receive, mark

    def send(self, message):
        return self._sender(message)

    def receive_available(self):
        return self._receive()

    def mark_influenced(self, message_id):
        """Receiver explicitly reports that a delivered message affected a decision."""
        self._mark(message_id)


class PerfectMessageBus:
    def __init__(self, agent_ids, clock):
        if len(set(agent_ids)) != len(agent_ids):
            raise ValueError('Duplicate agent IDs')
        self._queues = {agent: [] for agent in agent_ids}
        self._clock = clock
        self._sequences = {}
        self._seen_ids = set()
        self._delivered = {}
        self._log = []

    def endpoint(self, agent_id):
        if agent_id not in self._queues:
            raise ValueError('Unknown endpoint')
        return AgentEndpoint(lambda m: self._send(agent_id, m),
                             lambda: self._receive(agent_id),
                             lambda mid: self._mark(agent_id, mid))

    def _send(self, agent_id, message):
        # Snapshot/validate at the boundary so sender mutation cannot affect delivery.
        message = AgentMessage.from_json(message.to_json())
        if message.sender_id != agent_id:
            raise ValueError('Endpoint cannot impersonate another sender')
        if any(r not in self._queues for r in message.recipient_ids):
            raise ValueError('Unknown recipient')
        now = self._clock()
        if message.timestamp > now:
            raise ValueError('Future creation time')
        key = (message.sender_id, message.mission_id)
        if message.message_id in self._seen_ids or message.sequence_number <= self._sequences.get(key, 0):
            raise ValueError('Duplicate ID or nonmonotonic sender/mission sequence')
        self._seen_ids.add(message.message_id)
        self._sequences[key] = message.sequence_number
        for recipient in message.recipient_ids:
            record = dict(message_id=message.message_id, message_type=message.message_type.value,
                sender_id=message.sender_id, recipient_id=recipient, mission_id=message.mission_id,
                sequence_number=message.sequence_number, creation_time=message.timestamp,
                sent_time=now, scheduled_delivery_time=now, actual_delivery_time=None,
                size_bytes=len(message.to_json().encode('utf-8')),
                expires_at=message.timestamp+message.time_to_live_s,
                status='queued', influenced_decision=False)
            self._log.append(record)
            self._queues[recipient].append((message.to_json(), record))
        return message.message_id

    def _receive(self, agent_id):
        now = self._clock()
        items, self._queues[agent_id] = self._queues[agent_id], []
        delivered = []
        for serialized, record in items:
            if now >= record['expires_at']:
                record['status'] = 'expired'
                continue
            record.update(status='delivered', actual_delivery_time=now)
            self._delivered[(agent_id, record['message_id'])] = record
            delivered.append(AgentMessage.from_json(serialized))
        return delivered

    def _mark(self, agent_id, message_id):
        record = self._delivered.get((agent_id, message_id))
        if record is None:
            raise ValueError('Cannot mark an undelivered message')
        record['influenced_decision'] = True

    def logs(self):
        """Experiment logger only; never supply this bus to an agent."""
        return copy.deepcopy(self._log)


def new_message(message_type, sender_id, recipient_ids, mission_id, timestamp, sequence_number, payload, ttl=5.):
    return AgentMessage(str(uuid.uuid4()), message_type, sender_id, recipient_ids,
                        mission_id, timestamp, sequence_number, ttl, payload)
