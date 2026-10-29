# Phase 7 against Plan.pdf

The supplied plan defines Phase 7 as a perfect-communication inter-agent protocol, not the RF-loss/low-battery demonstration previously named Phase 7. The plan says to add communication degradation later (Phase 10) and decentralized task allocation in Phase 8. Experiment D remains a separate resilience experiment.

## Requirements and current implementation

| Plan requirement | Implementation | Validation / remaining work |
|---|---|---|
| 13 message types | `MessageType` in `agentic_uav/comm/protocol.py` | Every type round-trips and is sent in the mock demo |
| Common message envelope | `AgentMessage` | Strict JSON, type enum, IDs, finite times, positive sequence/TTL, recipient list, confidence |
| Agent-local send and receive | `AgentEndpoint.send(message)` and `receive_available()` | No public global-queue, other-memory, or ground-truth reads in agent code |
| Message logging | Per-recipient records from `PerfectMessageBus.logs()` for the experiment logger | Creation, send, scheduled/actual delivery, status, size, expiry, and explicit receiver-reported decision influence |
| Four deterministic agents exchange heartbeat/status while flying | `phase7_demo.py` | Mock in-air kinematics only; live four-drone flight remains unvalidated |
| Local team beliefs update only through delivery | `ProtocolAgent.receive()` | Tests verify beliefs do not update before inbox consumption |

The types are:

```text
HEARTBEAT STATUS_UPDATE
TASK_ANNOUNCEMENT TASK_BID TASK_AWARD TASK_ACCEPT TASK_RELEASE TASK_COMPLETE
INTENT_UPDATE TARGET_FOUND HELP_REQUEST ROLE_CHANGE MISSION_UPDATE
```

The envelope contains `message_id`, `message_type`, `sender_id`, `recipient_ids`, `mission_id`, `timestamp`, `sequence_number`, `time_to_live_s`, `payload`, and nullable `confidence`. The plan leaves per-type payload schemas unspecified; payload is currently a strict finite JSON dictionary. Application-specific payload schemas and consumers still need to be designed as allocation and coordination are implemented. Do not interpret enum coverage as a completed negotiation algorithm.

## Run

From the repository root, no simulator or LLM is needed:

```bash
python -u scripts/run_phase7_resilience.py \
  --ticks 20 --output-dir results/phase7/protocol
```

Default execution now runs the plan-aligned perfect-communication mock protocol. It writes:

- `messages.json`: per-recipient transport records.
- `beliefs.json`: each agent's own mock position, local team beliefs, and local action per tick.
- `summary.json`: message-type coverage and delivery/belief checks.

All four agents send heartbeat and status messages. Their next local action is determined from their delivered peer-airborne status. Drone1 also sends one protocol probe for every type; probes for task/role types are not task-allocation decisions and are not marked decision-influencing. A message is marked as influencing a decision only when the receiver explicitly reports its use; belief receipt alone is not enough.

Retain the original RF-loss/low-battery demo with:

```bash
python -u scripts/run_phase7_resilience.py --legacy-resilience
```

## Transport semantics

Infrastructure creates one registered endpoint per agent. Sending snapshots and validates the full message, checks sender identity and registered recipients, rejects duplicate message IDs and nonmonotonic sequences per sender/mission, and schedules delivery immediately. Actual delivery is logged on receiver polling; TTL is checked at that time. Expired messages never reach local beliefs. Recipient payload copies are independent. Influence can only be reported for a message delivered to that endpoint. `logs()` returns a snapshot for the experiment logger and must not be passed to agents. This is software API isolation, not a process-level security boundary.

Clocks are injected; all envelope timestamps must use the same simulation time basis. Perfect communication applies no RF drops, artificial delays, bandwidth limits, or partitions. Status can be queued, delivered, or expired; no deliberate dropped status occurs in this perfect transport. Controlled fault scheduling belongs to Phase 10.

## Scope

The old `CommBus`/`Message` APIs remain unchanged for existing ScenarioManager and reactive-relay callers. The new protocol coexists with that legacy transport; those callers and Experiment D are not silently migrated. Remaining integration includes per-type payload/consumer definitions, live four-drone adapters, Phase 8 auctions and leases, and later degradation/LLM integration against this common protocol.

```bash
python -m unittest discover -s tests -p 'test_phase7_protocol.py' -v
```

Tests cover all types, serialization, payload isolation, addressed delivery, TTL, sequence/ID rejection, sender impersonation, logs, receipt-only belief changes, and the four-agent mock demonstration.
