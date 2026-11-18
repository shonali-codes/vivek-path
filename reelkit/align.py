"""Forced-align an episode's VO against its script.json with PocketSphinx.

    python3 reelkit/align.py EY-02

Writes <EP>/build/words.json: [{seg, shot, w, s, e}] (times relative to the VO file).
Out-of-dictionary names get pronunciations from reelkit/extra.dict."""
import json, sys, os, subprocess
from pocketsphinx import Decoder, get_model_path
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from words import tokens

ep = os.path.abspath(sys.argv[1]); EP = os.path.basename(ep)
cfg = json.load(open(os.path.join(ep, "episode.json")))
vo = os.path.join(ep, "assets", f"{EP}_VO.wav")
M = get_model_path()
os.makedirs(os.path.join(ep, "build"), exist_ok=True)
dic = os.path.join(ep, "build", "align.dict")
base = open(M + "/en-us/cmudict-en-us.dict").read(); extra = open(os.path.join(HERE, "extra.dict")).read()
open(dic, "w").write(base + extra)
known = {l.split()[0].split("(")[0] for l in (base + extra).splitlines() if l.strip()}
script = json.load(open(os.path.join(ep, "script.json")))
toks = [(s["seg"], s["shot"], d, sp) for s in script for d, sp in tokens(s["text"], cfg.get("spoken", {}))]
spoken = [w for t in toks for w in t[3]]
oov = sorted({w for w in spoken if w not in known})
if oov:
    sys.exit(f"add pronunciations to reelkit/extra.dict for: {oov}")
pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", vo, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
d = Decoder(hmm=M + "/en-us/en-us", dict=dic, lm=None, samprate=16000, beam=1e-60, wbeam=1e-50, pbeam=1e-60, loglevel="ERROR")
d.set_align_text(" ".join(spoken))
d.start_utt(); d.process_raw(pcm, full_utt=True); d.end_utt()
segs = [(s.word.split("(")[0], s.start_frame / 100, (s.end_frame + 1) / 100) for s in d.seg()
        if s.word not in ("<s>", "</s>", "<sil>", "(NULL)")]
assert [w for w, _, _ in segs] == spoken, f"alignment failed: {len(segs)} of {len(spoken)} words"
out = []; i = 0
for seg, shot, disp, sp in toks:
    g = segs[i:i + len(sp)]; i += len(sp)
    out.append(dict(seg=seg, shot=shot, w=disp, s=round(g[0][1], 3), e=round(g[-1][2], 3)))
json.dump(out, open(os.path.join(ep, "build", "words.json"), "w"), indent=0)
print(len(out), "words; speech ends", out[-1]["e"])
for k in sorted({o["seg"] for o in out}):
    ws = [o for o in out if o["seg"] == k]
    print(f"SEG{k}: {ws[0]['s']:7.2f} – {ws[-1]['e']:7.2f}  '{ws[0]['w']}' … '{ws[-1]['w']}'")
