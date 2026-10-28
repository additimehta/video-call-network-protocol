# TCP-inspired congestion window experiment

This isolated experiment performed worse in loss/reordering scenarios and is
not enabled in the main implementation. It is a video adaptation of slow start
and additive-increase/multiplicative-decrease, not a complete TCP implementation.

Run from the repository root:

```sh
python3 code/retry_metrics.py code/scenarios/delay_jump.json code/experiments/tcp_aimd
PYTHONPATH=code/experiments/tcp_aimd:code python3 -m unittest discover -s code/experiments/tcp_aimd/tests
```

The window starts at ten MTU-sized packets. New ACKed bytes grow it during
slow start; afterward growth is MTU * newly_ACKed_bytes / cwnd. SACK loss
sets the window to half the smaller of outstanding bytes and cwnd, with a
two-MTU minimum. Timeout loss sets it to one MTU. A sequence boundary prevents
multiple reductions for packets already in flight at the first loss event;
ACKs for that episode do not grow the window. This boundary-based simplification
does not implement TCP Reno's full fast-recovery machinery.

Quality and probes are limited by min(estimated_rate, cwnd / SRTT), retaining
the 10% recovery reserve and the best-effort lowest quality. RTT, backlog, and
delivery-ratio signals are logged but no longer independently cut the bandwidth
estimate. Shared timeout backoff and deadline abandonment remain enabled.

## Matched results

134 simulations: 20 paired seeds each for mixed, reorder, delay_jump, plus
seven paired supplied scenarios. The before snapshot is the main implementation
with sender-wide timeout backoff, prior to this experiment. Exact matched
scenario paths were used within each pair. No glitches occurred in the
experimental runs.

| Scenario | Before mean score | Experimental mean score |
|---|---:|---:|
| mixed | 0.4079 | 0.0473 |
| reorder | 0.2061 | -0.9227 |
| delay_jump | 0.6815 | -0.2735 |

| Supplied scenario | Before | Experimental |
|---|---:|---:|
| clean | 0.835 | 0.998 |
| rate_drop | 0.428 | 0.444 |
| rate_swings | 0.457 | 0.541 |
| heavy_loss | 0.706 | -0.043 |
| bursty_loss | 0.789 | 0.246 |
| random_loss | 0.827 | 0.476 |
| rate_rise | 0.616 | 0.552 |

Mean missed frames increased from 170.8 to 702.9 out of 750 in reorder,
and mean freeze time rose from 1244 to 28144 ms. In delay_jump, mean missed
frames rose from 42.3 to 384.6. These are deadline/continuity regressions,
not corrupted playback.

The results are consistent with window cuts restricting frame delivery under
loss and delayed feedback. This does not establish that every TCP-inspired
controller would fail; this specific controller, recovery simplification,
and quality coupling were not suitable. In particular, ACKs for abandoned
packets do not grow cwnd, so deadline expiry changes the feedback behavior
relative to ordinary reliable TCP.

Raw paired metrics: ../../seed_results/aimd_comparison.csv.
