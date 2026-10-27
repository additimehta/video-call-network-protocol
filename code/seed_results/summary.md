Seed sweep: current call.py

20 seeds per scenario (1–20); supplied scenario settings unchanged.
call.py SHA-256: e47081600166048942d635640f4cab4de6a5ee1937d4fe733259ad0048f783a9

| Scenario | Mean score | Worst (seed) | Best (seed) | Mean freezes | Mean missed frames |
|---|---:|---:|---:|---:|---:|
| mixed | -0.105 | -0.168 (1) | 0.576 (4) | 1.6 | 385.8 |
| reorder | 0.254 | 0.254 (1) | 0.255 (6) | 0.0 | 0.0 |
| delay_jump | 0.672 | 0.606 (2) | 0.750 (19) | 0.6 | 7.9 |

Full metrics: results.csv. Per-run playback and packet logs: ../logs/<scenario>-seed-<NN>-code.{json,csv} (packet files end in -packets.csv).
Runs also recorded by the simulator in ../history.csv. Seeds can be reproduced by copying the corresponding supplied scenario and replacing its seed field.
Packet totals include setup traffic; exact retransmission counts are not exposed by the existing log format.
