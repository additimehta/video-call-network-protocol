"""Watch what the viewer saw in one or more runs, side by side.

Usage: python3 replay.py LOG [LOG ...]
       e.g. python3 replay.py logs/random_loss-code.json logs/random_loss-baseline.json

Writes replay.html in this directory; open it in a browser. It loads the
frames from clips/, so keep it in this directory.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>A1 replay</title>
<style>
  body { font-family: sans-serif; margin: 20px; }
  .runs { display: flex; flex-wrap: wrap; gap: 20px; }
  .run { position: relative; }
  .run img { width: 480px; height: 270px; background: #000; display: block; }
  .frozen, .glitch { position: absolute; top: 40px; left: 8px; background: #c00; color: #fff;
                     padding: 2px 8px; font-weight: bold; }
  .glitch { left: auto; right: 8px; background: #a0a; }
  input[type=range] { width: 480px; }
</style>
<p><button id="play">Play</button> <span id="clock"></span></p>
<p><input id="seek" type="range" min="0" max="1000" value="0"></p>
<div class="runs" id="runs"></div>
<script>
const RUNS = __RUNS__;
let t = RUNS[0].start, playing = false, last = null;
const START = RUNS[0].start, END = Math.max(...RUNS.map(r => r.end));

for (const r of RUNS) {
  r.el = document.createElement("div");
  r.el.className = "run";
  r.el.innerHTML = `<div>${r.name}: score ${r.score.toFixed(3)}, ${r.freezes} freezes</div>
    <img><div class="frozen">FROZEN</div><div class="glitch">GLITCH</div><div class="info"></div>`;
  document.getElementById("runs").appendChild(r.el);
  for (const [time, id, level] of r.screen) if (id !== null) new Image().src = src(r, id, level);  // preload
}

function src(r, id, level) {
  return `clips/${r.clip}/${level}/${String(id + 1).padStart(4, "0")}.jpg`;
}

function draw() {
  for (const r of RUNS) {
    let cur = null, pic = null, real = null;  // what went on screen last, the last drawable picture, the last real frame
    for (const s of r.screen) {
      if (s[0] > t) break;
      cur = s;
      if (s[1] !== null) pic = s;
      if (s[3] !== "glitch") real = s;  // as in the score, a glitch does not end a freeze
    }
    const img = r.el.querySelector("img");
    if (pic) img.src = src(r, pic[1], pic[2]); else img.removeAttribute("src");
    const since = real ? t - Math.max(real[0], START) : t - START;
    r.el.querySelector(".frozen").hidden = since < r.freeze_gap;
    r.el.querySelector(".glitch").hidden = !(cur && cur[3] === "glitch");
    r.el.querySelector(".info").textContent = !cur ? "" : cur[1] === null ? "garbled frame" :
      `frame ${cur[1]}, quality level ${cur[2]}` + (cur[3] === "late" ? ", late" : "");
  }
  document.getElementById("clock").textContent = ((t - START) / 1000).toFixed(1) + " s";
  document.getElementById("seek").value = 1000 * (t - START) / (END - START);
}

function tick(now) {
  if (!playing) return;
  if (last !== null) t = Math.min(END, t + now - last);
  last = now;
  draw();
  if (t >= END) playing = false;
  requestAnimationFrame(tick);
}

document.getElementById("play").onclick = () => {
  if (t >= END) t = START;
  playing = !playing; last = null;
  document.getElementById("play").textContent = playing ? "Pause" : "Play";
  if (playing) requestAnimationFrame(tick);
};
document.getElementById("seek").oninput = e => {
  t = START + (END - START) * e.target.value / 1000;
  draw();
};
draw();
</script>
"""

if len(sys.argv) < 2:
    sys.exit(__doc__)
runs = []
for path in sys.argv[1:]:
    with open(path) as f:
        log = json.load(f)
    runs.append({"name": "%s (%s)" % (log["impl"], log["scenario"]), "clip": log["clip"],
                 "score": log["score"], "freezes": log["freezes"], "freeze_gap": log["freeze_gap_ms"],
                 "start": log["start_ms"], "end": log["end_ms"], "screen": log["screen"]})

out = os.path.join(HERE, "replay.html")
with open(out, "w") as f:
    f.write(PAGE.replace("__RUNS__", json.dumps(runs)))
print("wrote", os.path.relpath(out))
