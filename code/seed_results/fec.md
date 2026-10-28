# XOR FEC implementation and comparison

**Historical experiment:** FEC was removed at the user's request. Active code uses the pre-FEC SACK implementation with the late-ACK bandwidth fix. The results below describe the removed experiment.

## Experimental implementation

One zero-padded XOR parity packet protects frames with at least four data packets. For assignment frame sizes this enables FEC at levels 2 and 3; levels 0 and 1 retain ordinary SACK recovery and the previous 10% retry reserve. Parity costs are explicitly included in quality selection and probes instead of adding a second 10% reserve.

Video headers remain !BIdHH (17 bytes). PARITY type 0x12 reuses the packet-index field for the final data-payload length and the packet-count field for the number of data packets. The parity payload is CHUNK=1483 bytes; its SACK index is the data packet count, immediately after the data indices. Padding is removed using the final payload length. Every packet remains within the 1500-byte MTU.

The receiver can reconstruct one missing data piece if parity and all other data pieces arrive by the frame deadline. Two missing pieces require at least one retransmission before XOR can recover the other. Receipt of reconstructed pieces is reported using ACK type 0x13: the existing !BIdQ header, a two-byte recovered index, then normal SACK ranges. This recovered-index label is retained for subsequent reports so reordered/lost ACKs do not turn reconstruction into an apparent original-packet RTT sample. Reconstructed pieces release sender window space, but do not contribute synthetic received bytes, probe acknowledged-byte totals, RTT, or late-ACK timing. Actual later arrivals are counted once as network traffic.

Parity itself is not retransmitted. Fast gap retransmissions wait while parity is still outstanding or awaiting transmission for that frame; existing data retry timers remain the fallback. Payload and parity storage expires just after the 200 ms deadline.

## Supplied scenarios

| Scenario | Before FEC | Current FEC |
|---|---:|---:|
| bursty_loss | 0.712 | 0.738 |
| clean | 1.000 | 1.000 |
| delay_jump | 0.852 | 0.853 |
| heavy_loss | 0.488 | 0.671 |
| mixed | 0.587 | 0.479 |
| random_loss | 0.995 | 1.000 |
| rate_drop | 0.656 | 0.656 |
| rate_rise | 0.712 | 0.668 |
| rate_swings | 0.546 | 0.524 |
| reorder | 0.342 | 0.389 |

All supplied scenarios have zero glitches; clean shows all 750 frames in time at level 3. Wall-clock runtime per supplied run was 0.25–0.86 seconds.

## Matched seeds

Five seeds per scenario; before/after implementations use identical scenario paths and settings. Scenario filenames differ from earlier investigations, so compare only matched rows within this experiment.

| Scenario | Mean before | Mean FEC | Improved / Worse / Equal |
|---|---:|---:|---|
| heavy_loss | 0.443 | 0.649 | 5 / 0 / 0 |
| mixed | 0.583 | 0.572 | 1 / 4 / 0 |
| bursty_loss | 0.712 | 0.700 | 2 / 3 / 0 |
| reorder | 0.304 | 0.312 | 2 / 1 / 2 |

FEC is not a uniform performance improvement. It helps the independent heavy-loss scenario, but one parity packet cannot recover an entire loss burst, and the extra traffic can make capacity-change scenarios worse. The supplied mixed regression is larger than the matched five-seed average regression. Retaining the implementation does not establish an optimal FEC policy.

## Validation

34 unit tests pass, including recovery of every missing position for both protected assignment frame sizes, parity arriving first/last, final-payload trimming, delayed originals and duplicates, two-loss fallback, lost parity, exact-deadline and late arrivals, bandwidth/window accounting, recovered-ACK timing exclusion, and parity-before-fast-retry behavior.

Earlier experiments tried FEC on every frame, adding parity on top of a 10% reserve, and protecting only frames with at least eight data packets. These were not retained. Sending fast retransmissions before giving parity a chance also hurt clean performance. Simulator history retains these runs.

Raw results: fec_supplied.json and fec_seeds.csv.

Before-FEC call.py SHA-256: e2f42e1c5f4ce93f67c499307294e75dd8f33ecb0adc83d2a9e099150f2a78d7
Current call.py SHA-256: 4b5d5cd45050b8ed1a24cf08da88b6897ee82858787f57ad47183d8e11091211
