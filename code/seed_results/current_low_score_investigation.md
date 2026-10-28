# Current low-score investigation

The current implementation was run on all ten supplied scenarios. Six scenarios were additionally observed using runtime wrappers around quality selection, receiver rate reports, retransmissions, receiver packet processing, and simulator link submissions. The transport implementation was not edited. Instrumented scores reproduced the ordinary supplied runs. Simulator link queue inspection is diagnostic only and must not be used by submitted transport code.

## Findings

- reorder (0.342): no network losses or queue drops, but 1,556 timer retransmissions and 101 gap retransmissions; 1,642 duplicate receipts. Retry bytes comprise approximately 46–48% of transmitted bytes. Ordinary forward queue waits have medians of 0–7 ms per five-second phase. Median estimated rate falls from 1,800 kbps early to 399 kbps in the final phase. All six completed quality probes fail their health check. Fixed retry timeout is 100 ms, while independent forward and reverse jitter can each add up to 120 ms. Timing observations therefore confuse harmless jitter with overload, while retries waste bandwidth. Most score loss is low quality rather than missing playback.

- heavy_loss (0.488): 222 frames missing, 4,760 ms frozen, 300 queue drops. Retransmission bytes are approximately 15–32% of traffic across phases, exceeding the fixed 10% quality-selection reserve in every phase. Several phases offer about 4.08–4.15 Mbps to a 4 Mbps link. Level 3 is repeatedly promoted by probes whose success threshold is only 85% of its required original-data rate. This threshold does not validate a sufficient recovery margin or complete-frame playback. Of incomplete frames seen at the receiver, 113 lack only one piece by the deadline. Actual loss, wasted recovery, and large frames all contribute; the score contribution of each mechanism has not been isolated by ablation.

- rate_swings (0.546): 67 frames missing, 2,440 ms frozen, 643 queue drops despite zero configured random loss. During low-capacity phases, median queue wait is 106–122 ms and retries account for 36–43% of traffic. Capacity rises at 10 and 20 seconds, but level 3 probes succeed only around 14.55 and 24.71 seconds. Thus much of each high-capacity period is spent at lower quality, and promotion occurs just before the next capacity drop. Probes increase one level at a time with a two-second cooldown; the window also retains the initial-rate floor.

- bursty_loss (0.712): 83 frames missing, 2,280 ms frozen, 117 queue drops. Recovery bytes comprise approximately 10–24% of traffic by phase. Successful probes can promote high quality while only proving at least 85% of its nominal original-data throughput, without establishing enough headroom for loss bursts. Large frames require many pieces and bursts can erase multiple neighboring pieces. Distinguishing unavoidable losses from avoidable recovery/quality decisions requires a separate controlled experiment.

## Suggested investigation order

1. Test a reordering-tolerant recovery timer and stronger evidence before gap retransmissions, separately. Preserve deadline checks.
2. Test recovery-aware quality headroom or stricter probe acceptance in the loss scenarios.
3. Test faster but bounded recovery of quality after capacity increases, using matched seeds and checking overload after decreases.

These are proposed experiments, not implemented fixes. Raw phase measurements, probe outcomes, and rate samples are in current_low_score_investigation.json.
