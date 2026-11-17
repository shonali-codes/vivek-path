import json, re
# Spoken forms for tokens that are written differently on screen
SPOKEN = {"6:33": ["six","thirty","three"], "1863": ["eighteen","sixty","three"]}
def tokens(seg_text):
    """Return list of (display_word, [spoken words]) for one segment."""
    out=[]
    for raw in seg_text.split():
        if raw in ("—","-"): continue
        disp = raw.strip()
        key = re.sub(r"[^\w:]","",raw)
        spoken = SPOKEN.get(key) or [re.sub(r"[^a-z']","",raw.lower())]
        spoken=[s for s in spoken if s]
        if spoken: out.append((disp, spoken))
    return out
