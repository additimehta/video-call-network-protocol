# Forward-delay sending experiment (not retained)

The trial replaced both initial-send deadline checks and the resend deadline check with a recent forward-delay prediction plus the existing 40 ms margin. The prediction used at least three eligible forward samples from the last 500 ms, expressed as the recent baseline plus median excess above it (equivalent to their median delay); with insufficient samples it fell back to half measured RTT. Quality selection, byte window, adaptive timeout, and late-ACK bandwidth reduction were unchanged.

| Scenario | Before trial | Forward-delay rule |
|---|---:|---:|
| bursty_loss | 0.926 | 0.871 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.825 | 0.828 |
| heavy_loss | 0.748 | 0.744 |
| mixed | 0.377 | 0.113 |
| random_loss | 0.995 | 0.995 |
| rate_drop | 0.464 | -0.056 |
| rate_rise | 0.709 | 0.723 |
| rate_swings | 0.315 | 0.087 |
| reorder | 0.494 | 0.344 |

All supplied runs had zero glitches and clean remained 1.000, but the trial materially regressed multiple scenarios and was removed. 33 tests pass after restoring the exact pre-trial source. The ACK triggering index and separate path observations remain collected; they are not connected to sending decisions. Existing adaptive retry timing and the measured-RTT resend deadline experiment remain applied.

The trial scores demonstrate a regression, but its causes were not isolated by additional instrumentation. Do not claim that forward timing is inherently unusable or that any particular baseline/variation choice is proven optimal. Raw results: forward_send_supplied.json.
