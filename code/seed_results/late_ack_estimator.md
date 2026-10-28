# Late ACK estimator comparison

Late ACK timing is retained separately from RTT estimation, window sizing, and the acknowledged-byte counter used by probes. The estimator now treats at least three unretransmitted late ACK samples from the last 500 ms as slow feedback when their median confirmation delay exceeds the existing ACK RTT plus variation threshold. Bandwidth reductions still require a received-byte deficit; slow late feedback also prevents or ends higher-quality probes.

This is an overload heuristic, not a direct capacity measurement. ACK loss and reverse-path delays can still affect confirmation delay. The existing send/receive measurement intervals are not exactly aligned.

## Supplied scenarios

| Scenario | Before | After |
|---|---:|---:|
| bursty_loss | 0.718 | 0.712 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.852 | 0.852 |
| heavy_loss | 0.488 | 0.488 |
| mixed | -0.139 | 0.587 |
| random_loss | 0.995 | 0.995 |
| rate_drop | 0.656 | 0.656 |
| rate_rise | 0.712 | 0.712 |
| rate_swings | 0.546 | 0.546 |
| reorder | 0.342 | 0.342 |

All supplied runs have zero glitches; clean still displays all 750 frames in time. mixed improves from 347 to 696 frames in time, queue drops decrease from 866 to 36, and freeze time decreases from 15,080 to 760 ms. bursty_loss slightly regresses, so this is not a uniform improvement.

## Matched seeds

Baseline is the current implementation with late-ACK timing collection but without the new overload signal or probe guard. Both implementations use the same scenario paths and filenames; only the seed differs from the supplied configuration.

| Scenario | Seeds | Mean before | Mean after | Improved / Worse / Equal |
|---|---:|---:|---:|---|
| mixed | 20 | -0.061 | 0.578 | 20 / 0 / 0 |
| reorder | 5 | 0.303 | 0.304 | 1 / 0 / 4 |

24 unit tests pass. New tests cover the delivery-deficit guard, stale/retried/isolated timing samples, and higher-quality probe suppression.

Raw data: late_ack_estimator.json, late_ack_estimator_seeds.csv. Supplied mixed trace: mixed_late_ack_estimator.log.

The supplied mixed estimate drops from approximately 2,691 to 1,506 kbps at 15,653 ms. It can still temporarily underestimate capacity; the improvement does not establish that its estimate always equals link capacity.
