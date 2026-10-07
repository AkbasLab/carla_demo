import time
from dataclasses import dataclass, field
from typing import Dict, List, Callable, Any, Optional
from agentic_uav.comm.rf_model import RFPropagationModel
from agentic_uav.core.models import Position3D

@dataclass
class Message:
    sender_id: str
    recipient_id: str
    topic: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

class CommBus:
    """RF-constrained message bus simulating range limits and packet loss."""

    def __init__(self, rf_model: Optional[RFPropagationModel] = None):
        self._subscribers: Dict[str, List[Callable[[Message], None]]] = {}
        self.message_history: List[Message] = []
        self.rf_model = rf_model or RFPropagationModel()

    def subscribe(self, topic: str, callback: Callable[[Message], None]) -> None:
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)

    def publish(self, msg: Message, sender_pos: Optional[Position3D] = None, recipient_pos: Optional[Position3D] = None) -> bool:
        # Evaluate RF connectivity if position coordinates are provided
        if sender_pos and recipient_pos:
            if not self.rf_model.is_connected(sender_pos, recipient_pos):
                print(f"❌ [COMM_BUS:DROPPED] Packet '{msg.topic}' from {msg.sender_id} dropped (Out of RF Range).")
                return False

        self.message_history.append(msg)
        print(f"[COMM_BUS:DELIVERED] Packet '{msg.topic}' ({msg.sender_id} -> {msg.recipient_id})")

        if msg.topic in self._subscribers:
            for cb in self._subscribers[msg.topic]:
                cb(msg)
        return True
