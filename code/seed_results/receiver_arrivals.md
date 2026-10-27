# Receiver arrival measurements

Matched before/after runs use identical scenario settings, seeds, and scenario filenames. Baseline is the implementation immediately before the receiver-arrival patch. 140 runs total.

The SACK header now contains receiver time and cumulative unique video bytes (including video headers). The sender measures byte deltas over receiver-time intervals of at least 500 ms. Duplicate packets are counted once per call, even after receipt history cleanup. Lost reports are covered by later cumulative totals; reordered reports do not move the measurement backward. Measurements are processed even if no corresponding pending packets remain.

Existing rate decrease safeguards, quality probes, sliding window policy, and retry policy remain. Delivery rate is not an exact measurement of unused link capacity. The receiver retains a set of counted packet IDs for the lifetime of the call.

## Supplied scenarios

| Scenario | Before | After |
|---|---:|---:|
| bursty_loss | 0.734 | 0.699 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.623 | 0.852 |
| heavy_loss | 0.607 | 0.550 |
| mixed | -0.141 | -0.139 |
| random_loss | 0.995 | 0.995 |
| rate_drop | 0.652 | 0.656 |
| rate_rise | 0.743 | 0.736 |
| rate_swings | 0.567 | 0.601 |
| reorder | 0.254 | 0.341 |

## Seeds 1–20

| Scenario | Mean before | Mean after | Improved / Worse / Equal | Worst after |
|---|---:|---:|---|---:|
| mixed | -0.105 | -0.095 | 5 / 5 / 10 | -0.178 |
| reorder | 0.254 | 0.313 | 20 / 0 / 0 | 0.255 |
| delay_jump | 0.672 | 0.851 | 20 / 0 / 0 | 0.821 |

After call.py SHA-256: a5aa97cddf8b800461ead76c3795ee045e8a8960052a80818dc40b5a80ee8d95

Full metrics: receiver_arrivals.csv. Original seed-sweep files remain available separately.
