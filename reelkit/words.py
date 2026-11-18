import re

def tokens(seg_text, spoken_map=None):
    """Split one segment into (display_word, [spoken words]) pairs.
    spoken_map maps a written token (e.g. "1863") to how it is said."""
    spoken_map = spoken_map or {}
    out = []
    for raw in seg_text.split():
        if raw in ("—", "-", "–"):
            continue
        key = re.sub(r"[^\w:]", "", raw)
        spoken = spoken_map.get(key) or [re.sub(r"[^a-z']", "", raw.lower()).strip("'")]
        spoken = [s for s in spoken if s]
        if spoken:
            out.append((raw.strip(), spoken))
    return out
