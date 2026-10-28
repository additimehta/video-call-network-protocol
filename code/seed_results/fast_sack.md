# TCP-inspired three-packet SACK fast retransmission

## Current implementation

The 10 ms grace timer is replaced by an evidence threshold. For each still-pending packet in the same frame as an incoming SACK, count the distinct received packet indices strictly above its index across the validated, disjoint SACK ranges. At least FAST_RETRANSMIT_PACKETS=3 later received packets triggers check_fast_retransmit() to call resend() immediately. Retransmitted packets cannot fast-retry again, and resend() still enforces the existing delivery prediction and retry limit.

This is TCP-inspired rather than an exact implementation of TCP duplicate ACK counting. Classic TCP uses three duplicate cumulative ACKs; this custom protocol has selective ranges, so three distinct later received packets are stronger evidence than three copies of the same ACK. One cumulative SACK can establish the threshold if it reports three later packets; repeating a report with only one or two later packets never increases the count. See RFC 5681 section 3.2 (https://www.rfc-editor.org/rfc/rfc5681.html#section-3.2) and the SACK loss inference in RFC 6675 (https://www.rfc-editor.org/rfc/rfc6675.html).

Small frames and tail losses may have fewer than three later packets, so they rely on the existing adaptive timeout. Deep reordering can still trigger spurious fast retries. The same-frame restriction, timeout backoff, experimental two-retransmission limit, absolute deadline cleanup, late-ACK metadata, and ACK/rate/quality/window logic remain unchanged. The unused grace timestamp and grace counters were removed. Metrics retransmissions_sack_gap now count threshold-triggered fast retries.

## Supplied scenarios

| Scenario | 10 ms grace | Three-packet threshold |
|---|---:|---:|
| bursty_loss | 0.933 | 0.924 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.826 | 0.821 |
| heavy_loss | 0.840 | 0.843 |
| mixed | 0.581 | 0.600 |
| random_loss | 0.993 | 0.993 |
| rate_drop | 0.609 | 0.609 |
| rate_rise | 0.709 | 0.709 |
| rate_swings | 0.549 | 0.549 |
| reorder | 0.420 | 0.287 |

## Matched seeds

Five matched seeds per scenario with identical paths/settings within each pair.

| Scenario | Mean grace | Mean fast | Improved / Worse / Equal |
|---|---:|---:|---|
| reorder | 0.379 | 0.342 | 1 / 4 / 0 |
| heavy_loss | 0.837 | 0.832 | 1 / 4 / 0 |
| bursty_loss | 0.928 | 0.926 | 2 / 3 / 0 |
| mixed | 0.436 | 0.557 | 4 / 1 / 0 |

This is not uniformly better than the grace-period policy. Mixed improves on average, including recovery of one previously collapsing seed, but another mixed seed regresses from 0.579 to 0.407. Reorder regresses substantially in the supplied case and on average. Do not describe this as TCP eliminating reordering ambiguity.

## Validation

41 unit tests pass. Threshold tests cover waiting below three, repeated identical SACKs, gap ACKs before the threshold, same-frame isolation, tail-loss timeout fallback, sparse ranges, deadline rejection, and no extra fast retry after a timeout retransmission. Existing backoff, retry-limit, cleanup, ACK-byte, and RTT-ambiguity tests remain. All supplied/matched scenarios have zero glitches and clean remains 1.000. Instrumented paired runs also assert exact pending/window/timer accounting and cleanup by the final playback deadline.

Raw results: fast_sack_supplied.json, fast_sack_seeds.csv, and fast_sack_metrics.json. The threshold implementation is currently applied; prior grace results remain in sack_grace.md.
