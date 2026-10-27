# Seed investigation

The application implementation was not modified. Runtime observation wrappers recorded quality choices, bandwidth estimates, retry attempts, duplicate packet receipts, and sender state for five representative runs. Scenario names and seeds match the original sweep; scores reproduced exactly. Raw observations are in investigation.json.

## Results

| Run | Score | Important observation |
|---|---:|---|
| mixed, seed 1 | -0.168 | Estimate remains 3,000 kbps despite link falling to 1,500 kbps. No frames captured in the second half are displayed. |
| mixed, seed 4 | 0.576 | Estimate falls to 1,579.5 kbps at 7.49 seconds, before the link-rate drop. Lower quality avoids the collapse seen in seed 1. |
| reorder, seed 1 | 0.254 | All 750 frames displayed, but 737 use level 0. No actual link losses; 1,351 retransmissions and 1,351 duplicate packet receipts. |
| delay_jump, seed 2 | 0.606 | Actual bandwidth stays 4,000 kbps, but estimated bandwidth collapses after latency rises; 354 displayed frames use level 0. |
| delay_jump, seed 19 | 0.750 | Estimate settles around 1,119 kbps after latency rises; second-half playback mostly uses level 1. |

## 1. Jitter is being interpreted as reduced bandwidth

In reorder, the initial propagation RTT is 40 ms, but each direction adds up to 120 ms of random jitter. The healthy/slow-ACK threshold stays at initial RTT + 60 = 100 ms. Observed delivery delay is often 130–155 ms, even though the sampled forward network queue never exceeds about 6.3 ms.

The estimate falls from 1,800 kbps to about 429 kbps within the first second and about 241 kbps by the second second. Lower quality then sends too little data to demonstrate the unused link capacity. Every quality selection after two seconds fails the healthy check; no upward probes occur. This explains the stable minimum-quality score across seeds.

## 2. Immediate gap retries mistake reordering for loss

The sender retries an earlier pending packet as soon as any later received packet is reported, including across frames. This can be triggered by packet reordering or delayed/lost feedback. In reorder seed 1, all 1,351 retransmissions resulted in duplicate receipts despite zero network losses. Retry timers also contribute: the initial 100 ms timer is shorter than many normal ACK round trips under this jitter.

The counts establish wasted transmissions; they do not isolate how many were triggered by gaps versus timers. A gap is evidence of possible loss, not proof.

## 3. Mixed can lose the feedback needed to reduce its sending rate

With an initial RTT of 80 ms, the timeout is fixed at 140 ms. At that time the resend deadline test adds another 40 ms of propagation and 40 ms of playback margin, so an original packet is typically removed instead of retried. Later SACKs for removed packets cannot call record_delivery.

In seed 1, the rate estimate never changes from 3,000 kbps. After the link falls to 1,500 kbps, queueing increases, packets expire from tracking, and bandwidth feedback stops. The last sampled delivery-delay estimate remains 138.8 ms, just below the 140 ms unhealthy threshold; this stale value also allows repeated higher-quality probes. In the original sweep this seed has 824 queue drops, 415 missed frames, and 15.56 seconds of freezes.

Seed 4 happens to reduce its estimate before the drop, avoiding sustained overload. This explains much of the large seed sensitivity. It does not show that the early reduction was a correct measurement of the then-current link capacity.

## 4. Delay changes leave timing assumptions stale

In delay_jump, one-way propagation delay rises from 20 to 80 ms while bandwidth stays at 4,000 kbps. Propagation RTT therefore rises from 40 to 160 ms, yet the retry timer stays at 100 ms and the healthy threshold stays at 100 ms. Normal packets are retried before an ACK could return.

RTT sampling excludes retransmitted packets to avoid ambiguous samples. Because normal packets now time out before acknowledgment, the sampled ACK RTT stays near its old value (about 69 ms in seed 2). The rate estimator treats the resulting slow feedback as congestion, lowers quality, and the healthy check blocks upward probing. Thus most lost score is lower quality, rather than missing frames alone.

## Proposed next steps (not implemented)

1. Separate packet recovery deadlines from retention of delivery feedback, so late SACKs can still inform capacity estimates without keeping expired data in the byte window.
2. Revisit latency and jitter handling: avoid comparing every future delivery against the initial RTT plus a fixed margin. Timeout adaptation must also address the lack of unambiguous RTT samples after a delay jump.
3. Require stronger gap evidence or a short reordering allowance before an immediate retransmission.
4. Make capacity recovery possible when low offered load or harmless jitter prevents the current healthy check from permitting probes.

Changes should be reviewed first, tested separately, and compared on identical seeds. Keep the reverted window experiment out of this investigation: shrinking the window alone did not address these underlying feedback problems.
