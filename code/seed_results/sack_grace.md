# Deadline-aware SACK grace and retry backoff

## Current implementation

SACK gaps are restricted to earlier pending packet indices in the same frame as the incoming SACK. On the first gap observation, a 10 ms grace callback is scheduled only if it precedes the existing timeout. Further SACKs do not reset or duplicate it. ACKs during grace remove pending state, making the callback harmless. A gap callback also becomes harmless if a timeout has already retransmitted the packet. Gap retries remain limited to the first retransmission of a packet.

Timeouts retain the existing measured RTT/jitter formula. After each timeout-triggered retransmission, the next interval is multiplied by RETRY_BACKOFF_FACTOR (currently 2). A SACK-triggered retransmission does not itself increase timeout backoff. Timers are capped at capture + 200 ms, and an explicit expiration callback releases state instead of issuing an already-expired retry. Before every actual retry, the existing prediction now + ack_rtt_ms / 2 + 40 must precede capture + 200. This remains an approximate forward-delay prediction.

MAX_RETRANSMISSIONS=2 is an experimental, configurable limit, counting retransmissions rather than original sends. After the last permitted retry, an ACK can still clear the packet until the next timeout/deadline cleanup. Abandonment is idempotent, cancels the retry timer, removes the pending entry, subtracts its original byte count exactly once, and preserves the previous late-ACK metadata for one second.

ACK parsing/format, receiver behavior, quality selection, bandwidth-update equations, RTT ambiguity exclusions, and window-sizing formula were not changed. Recovery timing and earlier cleanup can nevertheless alter their observed inputs and resulting choices.

## Lightweight metrics

Sender.recovery_metrics contains retransmissions (total), retransmissions_timeout, retransmissions_sack_gap, grace_checks_scheduled, grace_checks_resolved_by_ack, abandoned_deadline, and abandoned_retry_limit. Missing keys read as zero because it is a Counter. Sender.retransmissions_by_attempt counts first, second, etc. retransmissions. Each pending packet also carries its current retry count. These counters do not control sending.

## Supplied scenarios

| Scenario | Before | After |
|---|---:|---:|
| bursty_loss | 0.926 | 0.933 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.825 | 0.826 |
| heavy_loss | 0.748 | 0.840 |
| mixed | 0.377 | 0.581 |
| random_loss | 0.995 | 0.993 |
| rate_drop | 0.464 | 0.609 |
| rate_rise | 0.709 | 0.709 |
| rate_swings | 0.315 | 0.549 |
| reorder | 0.494 | 0.420 |

All supplied runs have zero glitches; clean remains 1.000.

## Matched seeds

Five matched seeds per scenario, identical paths and settings within each pair. Filenames differ from prior experiments; compare only matched rows within this report.

| Scenario | Mean before | Mean after | Improved / Worse / Equal |
|---|---:|---:|---|
| reorder | 0.420 | 0.379 | 2 / 3 / 0 |
| heavy_loss | 0.746 | 0.837 | 5 / 0 / 0 |
| bursty_loss | 0.928 | 0.928 | 3 / 2 / 0 |
| mixed | 0.362 | 0.436 | 3 / 2 / 0 |
| rate_swings | 0.482 | 0.541 | 3 / 2 / 0 |

This is not a uniform improvement. In particular, reorder regresses on average, and mixed seed 2 regresses from 0.482 to -0.153 despite its higher mean. More seeds and recovery/estimator interaction analysis are needed before treating this as a robust final policy.

## Backoff and limit experiment

Supplied heavy_loss, bursty_loss, mixed, and reorder were separately run with limits 1, 2, and 3 and with backoff disabled (factor 1). Their scores were identical across those settings. Only first retransmissions occurred in these supplied runs: the 200 ms deadline and delay prediction prevented a second actual retry. Thus these results do not establish an optimal retry limit or attribute score changes to exponential backoff. In-memory parameter overrides are recorded in sack_grace_ablations.json; source fingerprints alone do not distinguish those ablations.

The default supplied metrics are:

| Scenario | Timeout retries | SACK retries | ACKs resolving grace |
|---|---:|---:|---:|
| heavy_loss | 198 | 984 | 314 |
| bursty_loss | 181 | 231 | 425 |
| mixed | 0 | 2 | 328 |
| reorder | 68 | 55 | 32 |

## Validation

39 unit tests pass. Twelve new advancing-clock tests cover grace timing, ACK arrival during grace, duplicate SACKs, same-frame restriction, timeout precedence/races, deadline rechecking, exponential backoff, configurable retry limits, cleanup by the frame deadline, ambiguous RTT exclusion, and single-release/single-count behavior. Existing recovery tests were updated for deferred gap handling.

The matched/ablation runner additionally asserted that outstanding bytes equal the sum of pending original packet lengths, that retry-timer keys match pending keys, and that no pending entries survive the final playback deadline. All observed runs passed those assertions and had zero glitches. Instrumented runs finished in at most 0.45 seconds excluding process startup.

Raw files: sack_grace_supplied.json, sack_grace_seeds.csv, sack_grace_ablations.json, and sack_grace_metrics.json.
