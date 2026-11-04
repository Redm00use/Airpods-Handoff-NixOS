---
name: handoff-architecture
description: Design or evaluate changes to the AirPods ownership FSM, AACP host behavior, communication priorities, audio recovery and architectural trade-offs. Use for cross-module changes, not routine edits.
---
1. Map states, events and ownership authorities from current code; distinguish Linux policy from AirPods firmware behavior.
2. Specify explicit invariants: active local call guard, remote call/unknown protection, event ordering, single/bounded recovery, startup and resume baselines.
3. Consider failure modes: simultaneous play, muted calls, late ACK, interrupted remote call, sleep/wake, BlueZ alive but PipeWire broken.
4. Offer a small decision record with alternatives, consequences, implementation phases and testable acceptance criteria.
5. Avoid unsupported assertions about iCloud/Apple protocol parity.
