# Removing the minimum ACK-delay margin

Changed `allowable_ack_rtt_ms()` from `SRTT + max(20, 4 * variation)` to `SRTT + 4 * variation`. This shared function affects retry timeouts, slow-ACK detection, and quality-probe eligibility. Other transport policies are unchanged.

Compared snapshots of the before/after implementation against identical supplied scenario paths in a temporary directory. Original scenario files and logs were preserved. Scores below are simulator output rounded to three decimals.

| Scenario | Before | No minimum margin |
|---|---:|---:|
| bursty_loss | 0.924 | 0.826 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.821 | 0.821 |
| heavy_loss | 0.843 | 0.843 |
| mixed | 0.600 | 0.600 |
| random_loss | 0.993 | 0.993 |
| rate_drop | 0.609 | 0.609 |
| rate_rise | 0.709 | 0.709 |
| rate_swings | 0.549 | 0.542 |
| reorder | 0.287 | 0.288 |

All ten scenarios completed with zero glitches for both versions. Clean retained 750 frames shown in time. Bursty loss regressed substantially; this change is not an overall improvement on supplied cases. These are single supplied-seed results, not a multi-seed comparison. The causal contributions of retry timing versus the shared quality/slow-ACK threshold were not isolated.

Updated existing unit-test timings to the new policy while retaining retry-limit, backoff, ACK ambiguity, and cleanup assertions.
