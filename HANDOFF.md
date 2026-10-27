# call.py handoff — October 26, 2026

Resume by reading this note, `code/call.py`, and the reports linked below.

## Unresolved problem and scope

The central problem is deciding how much video to send as network conditions change. The scope is bandwidth estimation, quality adaptation, and their interaction with packet recovery. We do not yet have a reliable way to distinguish jitter, changing propagation delay, and congestion.

1. **Underestimating capacity:** In `reorder`, delayed feedback causes the estimate to fall and video quality to decrease. Lower-quality traffic then produces low measured throughput even when spare capacity exists. Probe eligibility can prevent recovery. Measured delivery rate is not the same as available link capacity.
2. **Missing capacity drops:** In bad `mixed` runs, the estimate stays high after the link rate falls. Excess traffic creates queues and frames miss their deadlines. Receiver-arrival measurements have not reliably resolved this.
3. **Ambiguous delay signals:** Timing checks influence bandwidth reductions, quality probes, and retries. A slow acknowledgment can reflect jitter, propagation changes, forward queueing, or return-path effects. The latest adaptive threshold helped some cases but hurt others.
4. **Unnecessary recovery traffic:** Immediate gap retransmissions can mistake reordering or delayed feedback for loss. Retry timers still use the initial RTT, so a latency increase can trigger retries before normal feedback could arrive.

These mechanisms were observed in earlier traces, but their individual contributions have not been isolated under the latest implementation. Do not present every historical observation as a freshly confirmed diagnosis of current code.

## Current implementation state

- Main implementation: `code/call.py`; changes are uncommitted.
- Sliding byte window sends multiple packets without waiting for each ACK. Quality is fixed within each frame.
- SACK feedback contains a frame ID and inclusive received packet-index ranges. Sender retries exposed earlier gaps once immediately; timers handle further recovery.
- ACK header is `!BIdQ`: type, frame ID, receiver timestamp, cumulative unique received video bytes. SACK ranges use `!HH`.
- Receiver-arrival measurements are applied over receiver-time intervals of at least 500 ms. Duplicate counting survives receipt-history cleanup. Old/reordered reports do not move measurement state backward. Later totals cover lost reports.
- Receiver reports are processed even when their frame has no remaining pending packets at the sender.
- **Late-arrival byte counting remains enabled.** Excluding late arrivals was proposed but never approved or implemented. Do not assume that proposal is applied.
- Playback deadline is capture time + 200 ms. Sender can abandon frames/packets earlier if its delivery-margin check predicts they cannot arrive in time. Already-transmitted packets cannot be withdrawn from the network.
- Current quality formula explicitly compares `wire_bytes * FPS * 8` with 90% of estimated bandwidth. This was algebraically equivalent to the previous transmission-time calculation; it did not improve performance by itself.
- Window-rate calculation still uses `max(initial_rate, estimated_rate)`. An experiment removing that floor and updating the window on every rate update caused regressions and was reverted.
- **Latest adaptive delay threshold remains applied** in both quality-probe eligibility and slow-ACK detection: `ack_rtt_ms + max(20, 4 * rtt_variation_ms)`. No authorization to revert it was given.
- Retry timer remains initial `rtt_ms + 60`.
- Stop-and-wait experiments were explicitly deleted at the user's request. Their simulator history/log entries remain; there is no active experiment implementation to resume.

## Evidence and results

- [Initial seed sweep](code/seed_results/summary.md), [raw results](code/seed_results/results.csv): seeds 1–20 for `mixed`, `reorder`, and `delay_jump`.
- [Detailed investigation](code/seed_results/investigation.md), [raw instrumentation](code/seed_results/investigation.json): observations from before receiver-arrival measurements. Representative seeded scores reproduced the original sweep.
- [Receiver-arrival comparison](code/seed_results/receiver_arrivals.md), [raw results](code/seed_results/receiver_arrivals.csv): 140 matched before/after runs. Seed means changed from -0.105 to -0.095 for mixed, 0.254 to 0.313 for reorder, and 0.672 to 0.851 for delay_jump. Supplied heavy_loss and bursty_loss regressed.
- [Adaptive-threshold comparison](code/seed_results/adaptive_delay.md), [raw results](code/seed_results/adaptive_delay.csv): 140 matched before/after runs. This is the latest change.

Latest seed means (1–20):

| Scenario | Before adaptive threshold | Current |
|---|---:|---:|
| mixed | -0.095 | -0.061 |
| reorder | 0.313 | 0.296 |
| delay_jump | 0.851 | 0.851 |

Latest supplied-case regressions include heavy_loss (0.550 → 0.488), rate_rise (0.736 → 0.712), and rate_swings (0.601 → 0.546). Clean remains 1.000. Do not describe the adaptive threshold as an overall improvement.

The last unit-test run passed 18 tests:

```sh
cd code
python3 -m unittest discover -s tests
```

Run a supplied scenario from the repository root:

```sh
python3 code/sim.py code/scenarios/mixed.json
```

For matched seed comparisons, copy scenario JSONs to a temporary directory and change only `seed`. Keep the same scenario filename across implementations: filenames affect joining/setup and can change timing. The original sweep names were `<scenario>-seed-<NN>.json`. Preserve supplied scenarios and `code/history.csv`; simulator runs append history and generate logs.

## How to continue

- The user wants the unresolved problems and scope explained plainly, rather than another recap of what works.
- **Show proposed code changes in chat and get explicit approval before editing implementation code.** Keep names descriptive and explanations simple. The user also requested short comments above functions and fewer redundant inline comments.
- Avoid stacking more changes onto the estimator without isolating their effects. A reasonable next investigation is to trace current `mixed` failures across the link-rate drop, comparing rate samples, quality choices, queued frames, expired tracking, and successful playback.
- Investigate before claiming a cause is confirmed. Any proposed next fix still needs review and approval.
- Nothing is committed. Do not overwrite the user's edits or treat all existing modifications as disposable.
