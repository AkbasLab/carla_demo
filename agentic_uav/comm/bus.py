import time
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any

@dataclass
class Message:
    sender_id: str
    recipient_id: str  # Specific vehicle_id, 'BASE_STATION', or '*' for broadcast
    topic: str         # e.g., 'TARGET_DISCOVERED', 'RELAY_REQUEST', 'TELEMETRY'
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

class CommBus:
    """Simulates local RF/Ad-hoc network packet routing between UAVs."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Message], None]]] = {}
        self.message_history: List[Message] = []

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> None:
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)

    def publish(self, msg: Message) -> None:
        self.message_history.append(msg)
        print(f"[COMM_BUS] Packet '{msg.topic}' broadcasted by {msg.sender_id} -> {msg.recipient_id}")
        
        # Route to subscribers matching topic
        if msg.topic in self._subscribers:
            for cb in self._subscribers[msg.topic]:
                cb(msg)
