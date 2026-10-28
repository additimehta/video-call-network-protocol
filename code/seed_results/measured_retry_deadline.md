# Measured RTT resend deadline experiment

The adaptive retry timer remains enabled. Only resend() changes its delivery prediction: clock.now() + ack_rtt_ms / 2 + 40 is compared with capture_time + 200. The two initial-transmission checks in send_waiting() still use initial RTT. No additional cap was added to the retry timer. Half of measured ACK turnaround is an approximation of forward delay, not a guarantee.

| Scenario | Adaptive timer, initial RTT deadline | Adaptive timer, measured RTT deadline |
|---|---:|---:|
| bursty_loss | 0.843 | 0.926 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.820 | 0.825 |
| heavy_loss | 0.440 | 0.748 |
| mixed | 0.589 | 0.377 |
| random_loss | 0.995 | 0.995 |
| rate_drop | 0.631 | 0.464 |
| rate_rise | 0.743 | 0.709 |
| rate_swings | 0.513 | 0.315 |
| reorder | 0.331 | 0.494 |

26 unit tests pass, including cases where measured RTT rises above or falls below initial RTT and changes whether retransmission is allowed. All supplied scenarios have zero glitches and clean remains 1.000. These results cover supplied seeds only.

The new check is currently applied at the user's request. It helps supplied heavy_loss, bursty_loss, and reorder, but materially regresses mixed, rate_drop, and rate_swings. It is not established as a uniformly better submission candidate. Raw results are in measured_retry_deadline.json.
