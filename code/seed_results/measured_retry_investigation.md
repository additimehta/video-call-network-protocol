# Why measured-RTT resend deadlines regressed some scenarios

Only the resend deadline condition differs between paired runs. The before variant substitutes initial RTT in that condition in memory; the after variant runs the current source. Adaptive retry timers and all other control logic remain identical. Wrappers record retry/expiration decisions, frame completion, rate updates, quality probes, RTT, window blocking, and link queues. Packet-level retry counts track repeated sends of the same frame/index, avoiding counting newly sent queued packets as retransmissions. Transport source was not edited.

| Scenario | Score before → after | Frames complete before → after | Freeze ms before → after |
|---|---|---|---|
| mixed | 0.589 → 0.377 | 707 → 583 | 0 → 4840 |
| rate_drop | 0.631 → 0.464 | 717 → 630 | 1480 → 4880 |
| rate_swings | 0.513 → 0.315 | 668 → 559 | 3520 → 7720 |
| rate_rise | 0.743 → 0.709 | 731 → 729 | 560 → 1040 |

## Confirmed mechanisms

- The changed condition uses ACK turnaround / 2 + 40 ms as a forward-delivery prediction. ACK turnaround includes reverse-path delays and variable queueing; halving it is not an exact measurement of future forward delivery. This condition can expire a packet earlier than the previous rule. Expiration releases window space and moves feedback into late-ACK history instead of normal delivery/RTT/probe counters. Consequently, the change also alters future estimates, probes, and timers.

- mixed: the before run reduces its estimate from 3000 to 1899 kbps at about 10.055 seconds, before the actual 15-second capacity drop. This early reduction is not proof of a correct capacity estimate, but it avoids later sustained overload. The after run stays at 3000 until about 20.227 seconds, when it reduces to 1505. During 15–20 seconds, median RTT is about 237 ms, median forward queue wait about 125 ms, and window blocking about 89%. Late receiver packets increase from 30 to 607. There are also six rejected retry opportunities for packets that were the sole missing piece at deadline and could fit the observed forward queue even with maximum configured jitter, assuming the retry was not randomly lost. Example: frame 93/piece 4 is rejected at 4092.835 ms with RTT 117.281 ms; its deadline is 4174 ms, and observed link state gives a counterfactual arrival interval of 4136.835–4166.835 ms. This establishes that the prediction can be too conservative, not that every regression is due to this one mechanism.

- rate_swings: after the first capacity drop, the before estimate falls to about 1478 kbps at 5.828 seconds. The after run retains 2390 kbps until about 8.347 seconds. During 5–10 seconds, median RTT rises from about 88 to 202 ms and median queue wait from 116 to 138 ms. The slow-ACK threshold follows measured RTT, so rising RTT can mask overload; this weakness already exists in the controller. Timer retransmissions fall from 324 to 20; completed frames fall from 668 to 559 and single-piece-incomplete frames rise from 23 to 100.

- rate_drop: timer retransmissions fall from 846 to 334, packet expirations rise from 255 to 500, completed frames fall from 717 to 630, and single-piece-incomplete frames rise from 1 to 49. This confirms less effective whole-frame recovery. Queue drops actually fall, so this is not simply more offered traffic. No newly rejected, not-yet-received packet in the diagnostic subset was guaranteed to fit the then-current forward queue even with maximum jitter. Therefore the evidence does not establish that those particular suppressed retransmissions would have succeeded; the full difference also reflects changed feedback and subsequent decisions.

- rate_rise: the successful level-3 probe finishes at 17.040 seconds instead of 15.800 seconds. That is direct evidence of slower quality recovery. Completed frames change only from 731 to 729; much of the score decline is lower quality, rather than missing frames.

## Limits

Simulator link-state inspection is for diagnosis only; submitted code cannot read it. Counterfactual arrival times use the queue at the rejected decision and do not guarantee survival under random loss or predict a full alternate run. These results cover the supplied seeds, not all networks. No fix is implemented by this investigation. Raw events and phase summaries are in measured_retry_investigation.json.
