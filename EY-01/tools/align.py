"""Forced-align the VO against script.json with PocketSphinx.
Aligns the whole VO in one pass (text is known), writes build/words.json:
[{seg, shot, w (display), s, e}] one entry per on-screen word."""
import json, sys, os, subprocess, numpy as np
from pocketsphinx import Decoder, get_model_path
sys.path.insert(0, os.path.dirname(__file__)); from words import tokens
VO = sys.argv[1]; OUT = sys.argv[2]
M = get_model_path()
dic = os.path.join(os.path.dirname(VO), "..", "build", "align.dict")
with open(dic, "w") as f:
    f.write(open(M+"/en-us/cmudict-en-us.dict").read()); f.write(open(os.path.join(os.path.dirname(__file__),"extra.dict")).read())
pcm = subprocess.run(["ffmpeg","-v","error","-i",VO,"-ac","1","-ar","16000","-f","s16le","-"],capture_output=True,check=True).stdout
script = json.load(open("script.json"))
toks=[]  # (seg, shot, disp, spoken list)
for s in script:
    for disp, sp in tokens(s["text"]): toks.append((s["seg"], s["shot"], disp, sp))
spoken = [w for t in toks for w in t[3]]
d = Decoder(hmm=M+"/en-us/en-us", dict=dic, lm=None, samprate=16000, beam=1e-60, wbeam=1e-50, pbeam=1e-60, loglevel="ERROR")
d.set_align_text(" ".join(spoken))
d.start_utt(); d.process_raw(pcm, full_utt=True); d.end_utt()
segs = [(s.word, s.start_frame/100, (s.end_frame+1)/100) for s in d.seg() if s.word not in ("<s>","</s>","<sil>","(NULL)")]
segs = [(w.split("(")[0], a, b) for w,a,b in segs]
assert [w for w,_,_ in segs] == spoken, f"alignment mismatch {len(segs)} vs {len(spoken)}"
out=[]; i=0
for seg, shot, disp, sp in toks:
    grp = segs[i:i+len(sp)]; i += len(sp)
    out.append(dict(seg=seg, shot=shot, w=disp, s=round(grp[0][1],3), e=round(grp[-1][2],3)))
json.dump(out, open(OUT,"w"), indent=0)
print(len(out), "words; last ends", out[-1]["e"])
for sgi in range(1,9):
    ws=[o for o in out if o["seg"]==sgi]; print(f"SEG{sgi}: {ws[0]['s']:7.2f} – {ws[-1]['e']:7.2f}  first='{ws[0]['w']}' last='{ws[-1]['w']}'")
