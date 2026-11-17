import json, sys
from faster_whisper import WhisperModel
m = WhisperModel(sys.argv[3] if len(sys.argv)>3 else "medium.en", device="cpu", compute_type="int8")
segs, _ = m.transcribe(sys.argv[1], word_timestamps=True, language="en", beam_size=5)
words=[]
for s in segs:
    print(f"[{s.start:6.2f}-{s.end:6.2f}] {s.text}", flush=True)
    words += [dict(w=w.word.strip(), s=round(w.start,3), e=round(w.end,3)) for w in s.words]
json.dump(words, open(sys.argv[2],"w"), indent=0)
