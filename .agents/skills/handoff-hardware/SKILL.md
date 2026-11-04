---
name: handoff-hardware
description: Prepare safe real-device AirPods handoff test plans and classify which claims are hardware-verified versus only simulated. Use when validating behavior with iPhone, Linux and physical AirPods.
---
1. Review `docs/` manual test matrix and README before proposing steps.
2. Use shadow mode when appropriate; remember it still opens AACP and requests status, not a passive sniffer.
3. Define repeatable scenarios: iPhone music vs local Play; ongoing local Discord/Telegram call vs iPhone activity; iPhone call interruptions; mute/silence; sleep/wake; sink recovery.
4. Record observable AACP/BlueZ/PipeWire state and whether audio was actually heard. Do not equate ACK with sound.
5. Avoid modifying pairing, adapter-wide identity or user audio devices without explicit approval.
