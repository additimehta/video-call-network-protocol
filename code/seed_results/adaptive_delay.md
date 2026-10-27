# Adaptive delay threshold comparison

Matched before/after runs use identical scenario settings, seeds, and scenario filenames. Baseline is the implementation immediately before this threshold change. 140 runs total.

Both quality-probe eligibility and slow-ACK detection now use measured ACK RTT + max(20 ms, 4 × RTT variation), replacing initial propagation RTT + 60 ms. Receiver-arrival measurements and other transport policies are unchanged.

## Supplied scenarios

| Scenario | Before | After |
|---|---:|---:|
| bursty_loss | 0.699 | 0.718 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.852 | 0.852 |
| heavy_loss | 0.550 | 0.488 |
| mixed | -0.139 | -0.139 |
| random_loss | 0.995 | 0.995 |
| rate_drop | 0.656 | 0.656 |
| rate_rise | 0.736 | 0.712 |
| rate_swings | 0.601 | 0.546 |
| reorder | 0.341 | 0.342 |

## Seeds 1–20

| Scenario | Mean before | Mean after | Improved / Worse / Equal | Worst after |
|---|---:|---:|---|---:|
| mixed | -0.095 | -0.061 | 4 / 0 / 16 | -0.162 |
| reorder | 0.313 | 0.296 | 13 / 7 / 0 | 0.266 |
| delay_jump | 0.851 | 0.851 | 0 / 0 / 20 | 0.821 |

After call.py SHA-256: 22462a9dc45ede84e1cb013fa707be05571280df51a2e6ffaaee69145854fa9c

Full metrics: adaptive_delay.csv. Original seed-sweep files remain available separately.
