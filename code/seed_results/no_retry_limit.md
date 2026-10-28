# Removing the retransmission-count limit

Removed MAX_RETRANSMISSIONS and both retry-limit abandonment paths. Recovery remains bounded by measured arrival prediction, capture + 200 ms timer cap, exponential timeout backoff, and at most one fast retransmission per packet. Retry counters remain for backoff and metrics.

Paired snapshots used identical supplied scenario files in a temporary directory. Scores are rounded simulator output; original logs and history were preserved.

| Scenario | Two-retry limit | No count limit |
|---|---:|---:|
| bursty_loss | 0.924 | 0.924 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.821 | 0.821 |
| heavy_loss | 0.843 | 0.843 |
| mixed | 0.600 | 0.600 |
| random_loss | 0.993 | 0.993 |
| rate_drop | 0.609 | 0.609 |
| rate_rise | 0.709 | 0.709 |
| rate_swings | 0.549 | 0.549 |
| reorder | 0.287 | 0.287 |

All runs completed with zero glitches. All 41 unit tests pass, including updated tests demonstrating a third timeout retransmission with normal backoff and deadline cleanup after more than two retries. These supplied-seed comparisons do not establish behavior across hidden scenarios or different seeds.
