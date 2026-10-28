# Adaptive retry timer experiment

The active retry timer now calls allowable_ack_rtt_ms(), returning smoothed measured ACK RTT + max(20 ms, 4 × RTT variation). RTT and variation are updated in the same function when a new eligible sample is provided. Retransmitted packets remain excluded from RTT updates. SACK gap retries, frame deadlines, late-ACK overload detection, and byte-window sizing are unchanged. FEC remains removed.

## Supplied scenarios

| Scenario | Fixed timeout | Adaptive timeout |
|---|---:|---:|
| bursty_loss | 0.712 | 0.843 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.852 | 0.820 |
| heavy_loss | 0.488 | 0.440 |
| mixed | 0.587 | 0.589 |
| random_loss | 0.995 | 0.995 |
| rate_drop | 0.656 | 0.631 |
| rate_rise | 0.712 | 0.743 |
| rate_swings | 0.546 | 0.513 |
| reorder | 0.342 | 0.331 |

All supplied runs have zero glitches, and clean remains perfect. 25 unit tests pass.

## Matched seeds

The two implementations use identical scenario paths/settings within each pair. Each scenario uses seeds 1–5.

| Scenario | Mean fixed | Mean adaptive | Improved / Worse / Equal |
|---|---:|---:|---|
| reorder | 0.304 | 0.351 | 4 / 1 / 0 |
| bursty_loss | 0.712 | 0.885 | 5 / 0 / 0 |
| heavy_loss | 0.443 | 0.364 | 2 / 3 / 0 |
| delay_jump | 0.850 | 0.848 | 3 / 2 / 0 |

## Observed behavior and limitations

The supplied reorder trace has 1,556 timer retries and 101 immediate gap retries with the fixed timer; adaptive timing changes these to 72 timer retries and 547 gap retries. Its median scheduled timeout is 234 ms (range 100–379.2 ms), versus a fixed 100 ms. Thus fewer timeout retries do not guarantee a higher score: gap retries still mistake reordering for loss, and larger timeouts can exceed frame usefulness.

The existing deadline check runs when a retry callback fires; an adaptive timer is not separately capped by the packet deadline. Tracking/window slots can therefore remain occupied beyond the point where a retry is useful. Actual losses can also leave too little time for recovery. These are known limitations, not fixes applied in this experiment. Heavy-loss seed 2 regresses from 0.461 to 0.169, so the adaptive version is not established as a uniformly better submission candidate.

Raw data: adaptive_retry_supplied.json and adaptive_retry_seeds.csv.
