# Triggered ACK path-delay measurements

ACK_HEADER is now !BIdQH (23 bytes): type, frame ID, receiver ACK-generation timestamp, cumulative unique received bytes, and the triggering packet index. Frame ID and triggering index together identify the exact packet whose arrival generated the timestamp. SACK ranges still follow the header. Sender validation requires the triggering index to be included in the received ranges.

For a triggering packet with retained send metadata and no retransmissions, forward delay is receiver_time - original_sent_at. Reverse ACK delay is sender_now - receiver_time. Forward samples are collected before SACK processing discards packet metadata, including separately retained expired metadata. Reordered reports and ambiguous retransmitted packets do not create forward samples. Receiver timestamps later than sender time are ignored for path measurements.

The forward baseline is the minimum valid sample within the last five seconds, bounded to 4096 samples. Current excess delay is latest forward sample minus baseline. Variation is an EWMA of absolute successive excess-delay differences (75% previous variation, 25% new difference). A rolling low baseline may eventually absorb a sustained queue or propagation change; it does not perfectly identify pure propagation, jitter, or congestion. ACK loss and retransmission exclusions also bias which samples are available.

These measurements are separate from existing RTT, bandwidth, quality, window, and retry decisions. They are collected for inspection before another control experiment. Existing measured-RTT retry deadline and adaptive retry timer remain applied. FEC remains removed.

At approximately 15.647 seconds in mixed, observed forward delay is 143.9 ms, recent baseline 44.3 ms, excess 99.6 ms, and reverse ACK delay 49.5 ms. This distinguishes increased forward delay from the reverse trip. In reorder near 15.367 seconds, a sample has 138.8 ms forward delay against a 28.7 ms baseline, demonstrating that excess can also reflect jitter rather than queueing. Raw observations are in path_timing_observations.json.

33 unit tests pass, covering triggering-index attribution, rolling baseline aging, expired metadata, retransmission exclusion, timestamp ordering, and receiver echoing the actual triggering index rather than the highest received index. All supplied runs have zero glitches and clean remains 1.000. Scores match the previous version to three decimal places; extra ACK bytes can change exact network timing even without changing control decisions.

| Scenario | Before | With path metadata |
|---|---:|---:|
| bursty_loss | 0.926 | 0.926 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.825 | 0.825 |
| heavy_loss | 0.748 | 0.748 |
| mixed | 0.377 | 0.377 |
| random_loss | 0.995 | 0.995 |
| rate_drop | 0.464 | 0.464 |
| rate_rise | 0.709 | 0.709 |
| rate_swings | 0.315 | 0.315 |
| reorder | 0.494 | 0.494 |

Raw supplied results: path_timing_supplied.json.
