---
name: handoff-debug
description: Diagnose AirPods Handoff failures involving AACP, BlueZ, PipeWire, Discord/Telegram calls, event races, interrupted audio and incorrect source ownership. Not for general code review.
---
1. Clarify expected vs observed transitions; inspect targeted events and sequence IDs, not entire journals.
2. Trace source ownership through AACP -> BlueZ transport -> PipeWire graph -> application audio. Each is a separate observation.
3. Check remote call/unknown guards, established local duplex/call protection, muted-but-active sessions, stale ACKs, cooldown and bounded recovery.
4. State a falsifiable root-cause hypothesis and identify the smallest regression test. Make the smallest fix if requested.
5. Do not log pairing secrets, invent hardware evidence, or retry device reconnect in loops.
