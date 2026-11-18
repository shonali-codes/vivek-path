"""Reel builder for *Swami Vivekananda — Who, before What* (@coffeehouseadda).

    python3 reelkit/align.py EY-02                 # forced alignment -> EY-02/build/words.json
    python3 reelkit/build.py EY-02                 # full render -> EY-02/out/<id>_<slug>.mp4
    python3 reelkit/build.py EY-02 --stills 3 50   # review frames at given seconds -> build/stills/

Each episode directory holds episode.json (look/timing config), script.json (segment text)
and assets/: <ID>_VO.wav, <ID>_bed_<raga>.wav, <ID>_shot<N>.(png|jpg). Shot 0, if present
in the config as cold_open, plays under the hook card before the VO starts.
"""
import json, math, os, subprocess, sys, glob, re
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

KIT = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30

# ---------------------------------------------------------------- series-wide look
XFADE = 0.5            # crossfade between shots (s)
KB_RATE = 0.0040       # Ken Burns zoom per second (1.0 -> ~1.10 over 25 s)
END_CARD = 3.0         # end card length (s)
TAIL_GAP = 0.6         # breath after last word before end card
CAP_Y = 1395           # caption centre line (lower third, above Reels UI)
CAP_SIZE = 108
CAP_MAX_W = W - 2 * 110  # title-safe width
WHITE = (255, 252, 244)
GOLD = (236, 190, 104)
LIGHT_GOLD = (250, 218, 150)
COLORS = {"white": WHITE, "gold": GOLD, "light_gold": LIGHT_GOLD}
BED_LUFS = -18.0       # bed level before ducking; under speech it sits ~10 dB below the VO
TARGET_LUFS = -14.0
TP_LIMIT = 0.85        # ≈ -1.4 dBFS sample peak ceiling

FONT = lambda w, s: ImageFont.truetype(os.path.join(KIT, "fonts", f"CormorantGaramond-{w}.ttf"), s)

EPDIR = None; CFG = {}
def A(*p): return os.path.join(EPDIR, *p)

def load_episode(path):
    global EPDIR, CFG
    EPDIR = os.path.abspath(path)
    CFG = json.load(open(A("episode.json")))
    CFG.setdefault("id", os.path.basename(EPDIR))

# ---------------------------------------------------------------- timeline
def timeline():
    co = CFG.get("cold_open")
    off = co["vo_offset"] if co else 0.0
    words = [dict(w, s=w["s"] + off, e=w["e"] + off) for w in json.load(open(A("build", "words.json")))]
    segs = {}
    for w in words:
        s = segs.setdefault(w["shot"], [w["s"], w["e"]])
        s[0] = min(s[0], w["s"]); s[1] = max(s[1], w["e"])
    shots = sorted(segs)
    sd = CFG.get("soft_dissolve", {})
    bounds = {}  # k -> (centre time, duration) of transition from shot k to the next
    if co:
        bounds[0] = (co["hold"] + co["dissolve"] / 2, co["dissolve"])
        shots = [0] + shots
    for k in shots[1:-1] if co else shots[:-1]:
        t = (segs[k][1] + segs[k + 1][0]) / 2
        bounds[k] = (t, sd["dur"] if sd.get("into") == k + 1 else XFADE)
    speech_end = max(w["e"] for w in words)
    ec_start = speech_end + TAIL_GAP
    total = ec_start + END_CARD
    win = {}
    for i, k in enumerate(shots):
        a = 0.0 if i == 0 else bounds[shots[i - 1]][0] - bounds[shots[i - 1]][1] / 2
        b = total if i == len(shots) - 1 else bounds[k][0] + bounds[k][1] / 2
        win[k] = (a, b)
    return dict(words=words, segs=segs, bounds=bounds, win=win, total=total, ec_start=ec_start,
                shots=shots, vo_offset=off)

def display_word(raw):
    m = CFG.get("display", {})
    return m.get(raw) or raw.strip("“”‘’\"'.,;:!?—–-()")

def caption_events(words, total):
    ev = []
    for i, w in enumerate(words):
        nxt = words[i + 1]["s"] if i + 1 < len(words) else total
        end = nxt if nxt - w["e"] < 0.6 else w["e"] + 0.30
        ev.append((w["s"], end, display_word(w["w"])))
    return ev

# ---------------------------------------------------------------- sprites
def text_sprite(text, font, fill, shadow=True, blur=9, pad=40, strength=200):
    l, t, r, b = font.getbbox(text)
    w, h = r - l + 2 * pad, b - t + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("L", (w, h), 0)
        ImageDraw.Draw(sh).text((pad - l, pad - t + 4), text, font=font, fill=strength)
        sh = sh.filter(ImageFilter.GaussianBlur(blur))
        tight = Image.new("L", (w, h), 0)
        ImageDraw.Draw(tight).text((pad - l, pad - t + 2), text, font=font, fill=150)
        tight = tight.filter(ImageFilter.GaussianBlur(2))
        a = np.maximum(np.asarray(sh, np.float32), np.asarray(tight, np.float32))
        img.putalpha(Image.fromarray(a.astype(np.uint8)))
    ImageDraw.Draw(img).text((pad - l, pad - t), text, font=font, fill=fill + (255,))
    return img

def runs_sprite(runs, font, blur=12, strength=255):
    """One line made of differently coloured runs, e.g. [["Swami Vivekananda","gold"],["?","white"]]."""
    text = "".join(r[0] for r in runs)
    l, t, r, b = font.getbbox(text); pad = 40
    w, h = r - l + 2 * pad, b - t + 2 * pad
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("L", (w, h), 0)
    ImageDraw.Draw(sh).text((pad - l, pad - t + 4), text, font=font, fill=strength)
    img.putalpha(sh.filter(ImageFilter.GaussianBlur(blur)))
    d = ImageDraw.Draw(img); x = pad - l
    for s, c in runs:
        d.text((x, pad - t), s, font=font, fill=COLORS[c] + (255,)); x += font.getlength(s)
    return img

def word_sprite(word):
    gold = {g.lower() for g in CFG.get("gold_terms", [])}
    color = GOLD if word.lower() in gold else WHITE
    size = CAP_SIZE
    while True:
        f = FONT("600-normal", size)
        l, _, r, _ = f.getbbox(word)
        if r - l <= CAP_MAX_W or size < 60: break
        size -= 4
    f = FONT("600-normal", size)
    spr = text_sprite(word, f, color)
    _, t, _, _ = f.getbbox(word)
    _, ht, _, hb = f.getbbox("x")
    ycenter = 40 + ((ht + hb) / 2 - t)  # centre on the x-height so all words sit on one line
    return spr, ycenter

def tracked_sprite(text, font, fill, track, blur=8, strength=230):
    """Letter-spaced text (small-caps kickers)."""
    widths = [font.getlength(c) for c in text]
    tw = int(sum(widths) + track * (len(text) - 1)) + 8
    _, t, _, b = font.getbbox(text)
    base = Image.new("RGBA", (tw, b + 8), (0, 0, 0, 0)); d = ImageDraw.Draw(base); x = 4
    for c, w in zip(text, widths):
        d.text((x, 0), c, font=font, fill=fill + (255,)); x += w + track
    pad = 40
    img = Image.new("RGBA", (base.width + 2 * pad, base.height + 2 * pad), (0, 0, 0, 0))
    a = base.getchannel("A"); sh = Image.new("L", img.size, 0); sh.paste(a, (pad, pad + 3))
    sh = sh.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: min(255, int(v * strength / 255 * 1.6)))
    img.putalpha(sh); img.alpha_composite(base, (pad, pad))
    return img

def _canvas():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    def put(spr, cy):
        img.alpha_composite(spr, (int(W / 2 - spr.width / 2), int(cy - spr.height / 2)))
    return img, put

def build_opener(o):
    """EY-01 style: kicker / name / rule / two-line hook in the upper third."""
    img, put = _canvas()
    put(tracked_sprite(o["kicker"], FONT("600-normal", 44), WHITE, 14), 238)
    size = 124
    while FONT("700-normal", size).getlength(o["name"]) > W - 2 * 90: size -= 2
    put(text_sprite(o["name"], FONT("700-normal", size), GOLD, blur=12, strength=255), 340)
    ImageDraw.Draw(img).line([(W / 2 - 110, 428), (W / 2 + 110, 428)], fill=GOLD + (220,), width=2)
    hf = FONT("500-italic", 64)
    put(text_sprite(o["hook"][0], hf, WHITE, blur=11, strength=255), 492)
    put(text_sprite(o["hook"][1], hf, LIGHT_GOLD, blur=11, strength=255), 568)
    return img

def build_hookcard(co):
    """Cold-open hook: bold serif lines made of coloured runs, centred on co['y']."""
    img, put = _canvas()
    lines = co["lines"]; y = co.get("y", 560)
    sizes = []
    for ln in lines:
        s = ln.get("size", 100); text = "".join(r[0] for r in ln["runs"])
        while FONT("700-normal", s).getlength(text) > W - 2 * 80: s -= 2
        sizes.append(s)
    gap = 1.18
    total_h = sum(s * gap for s in sizes); cy = y - total_h / 2
    for ln, s in zip(lines, sizes):
        put(runs_sprite(ln["runs"], FONT("700-normal", s)), cy + s * gap / 2); cy += s * gap
    return img

def build_endcard():
    img, put = _canvas()
    put(text_sprite("@coffeehouseadda", FONT("700-normal", 96), GOLD), 790)
    put(text_sprite("Follow the journey", FONT("500-italic", 66), WHITE), 905)
    ImageDraw.Draw(img).line([(W / 2 - 90, 1000), (W / 2 + 90, 1000)], fill=GOLD + (200,), width=2)
    f = FONT("600-normal", 44); fi = FONT("500-italic", 46)
    put(text_sprite("Based on", f, (225, 220, 210), blur=6), 1068)
    put(text_sprite("“Vivekananda: A Biography”", fi, WHITE, blur=6), 1128)
    put(text_sprite("by Swami Nikhilananda", f, (225, 220, 210), blur=6), 1188)
    put(text_sprite("(Ramakrishna–Vivekananda Center)", FONT("600-normal", 38), (200, 194, 182), blur=6), 1250)
    return img

# ---------------------------------------------------------------- per-frame
G = {}

def init_worker(epdir):
    load_episode(epdir)
    tl = timeline(); G["tl"] = tl; G["src"] = {}
    for k in tl["shots"]:
        p = [q for q in glob.glob(A("assets", f"{CFG['id']}_shot{k}.*")) if q.rsplit(".", 1)[1].lower() in ("png", "jpg", "jpeg")][0]
        im = Image.open(p).convert("RGB"); sw = 1620
        G["src"][k] = im.resize((sw, round(im.height * sw / im.width)), Image.LANCZOS)
    G["caps"] = caption_events(tl["words"], tl["total"])
    G["sprites"] = {}
    for _, _, w in G["caps"]:
        if w not in G["sprites"]: G["sprites"][w] = word_sprite(w)
    y = np.linspace(0, 1, H)[:, None]
    bot = np.clip((y - 0.58) / 0.25, 0, 1) ** 1.4 * 0.45
    G["shade_bottom"] = (1 - bot)[..., None].repeat(W, 1)
    G["shade_top"] = (np.clip((0.32 - y) / 0.32, 0, 1) ** 0.9 * 0.62)[..., None]
    G["shade_open"] = (np.clip((0.40 - y) / 0.40, 0, 1) ** 0.8 * 0.66)[..., None]
    G["shade_hook"] = (0.30 + 0.35 * np.exp(-((y - CFG.get("cold_open", {}).get("y", 560) / H) / 0.16) ** 2))[..., None]
    if CFG.get("title"):
        T = CFG["title"]["lines"]
        G["title"] = [text_sprite(T[0], FONT("600-normal", 76), WHITE, blur=12, strength=255),
                      text_sprite(T[1], FONT("500-italic", 70), LIGHT_GOLD, blur=12, strength=255)]
    G["endcard"] = build_endcard()
    if CFG.get("opener"): G["opener"] = build_opener(CFG["opener"])
    if CFG.get("cold_open"): G["hook"] = build_hookcard(CFG["cold_open"])

def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)

def shot_frame(k, t):
    a, b = G["tl"]["win"][k]
    src = G["src"][k]; sw, sh = src.size
    z = 1.0 + KB_RATE * max(0.0, t - a)
    cw, ch = sw / z, sw * H / W / z
    fx, fy = CFG.get("focus", {}).get(str(k), (0.5, 0.5))
    f = min(1.0, max(0.0, t - a) / max(1e-3, b - a)) * 0.6  # drift toward the subject as we push in
    cx = sw / 2 + (fx * sw - sw / 2) * f
    cy = sh / 2 + (fy * sh - sh / 2) * f
    cx = min(max(cx, cw / 2), sw - cw / 2); cy = min(max(cy, ch / 2), sh - ch / 2)
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    return np.asarray(src.transform((W, H), Image.EXTENT, box, Image.BICUBIC), np.float32)

def render(fi):
    tl = G["tl"]; t = fi / FPS
    active = [k for k in tl["shots"] if tl["win"][k][0] <= t < tl["win"][k][1]] or [tl["shots"][-1]]
    if len(active) == 1:
        frame = shot_frame(active[0], t)
    else:
        k1, k2 = active[:2]
        bt, bd = tl["bounds"][k1]
        m = smooth((t - (bt - bd / 2)) / bd)
        frame = shot_frame(k1, t) * (1 - m) + shot_frame(k2, t) * m
        sd = CFG.get("soft_dissolve", {})
        if sd.get("into") == k2 and sd.get("glow"):  # soft bloom through the dissolve
            glow = math.sin(math.pi * m) * sd["glow"]
            bl = np.asarray(Image.fromarray(frame.astype(np.uint8)).filter(ImageFilter.GaussianBlur(14)), np.float32)
            frame = frame * (1 - glow) + np.maximum(frame, bl * 1.08) * glow
    frame = frame * G["shade_bottom"]
    oa = ta = ha = 0.0
    if CFG.get("opener"):
        oa = 1 - smooth((t - CFG["opener"]["out"]) / 1.2)
        if oa > 0: frame = frame * (1 - G["shade_open"] * oa)
    if CFG.get("cold_open"):
        co = CFG["cold_open"]
        ha = 1 - smooth((t - co["hold"]) / (co["dissolve"] * 0.8))
        if ha > 0: frame = frame * (1 - G["shade_hook"] * ha)
    if CFG.get("title"):
        T = CFG["title"]
        ta = smooth((t - T["in"]) / 1.0) * (1 - smooth((t - T["out"] + 1.0) / 1.0))
        if ta > 0: frame = frame * (1 - G["shade_top"] * ta)
    ec = smooth((t - tl["ec_start"]) / 0.9)
    if ec > 0: frame = frame * (1 - 0.78 * ec)
    img = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8)).convert("RGBA")
    if ta > 0:
        for spr, cy in zip(G["title"], (270, 362)):
            overlay(img, spr, W / 2 - spr.width / 2, cy - spr.height / 2 + (1 - ta) * 10, ta)
    if oa > 0: overlay(img, G["opener"], 0, -(1 - oa) * 12, oa)
    if ha > 0: overlay(img, G["hook"], 0, -(1 - ha) * 12, ha)
    if ec > 0: overlay(img, G["endcard"], 0, (1 - ec) * 14, smooth((t - tl["ec_start"] - 0.25) / 0.9))
    for s, e, w in G["caps"]:  # word-by-word caption
        if s <= t < e:
            spr, yc = G["sprites"][w]
            fin = smooth((t - s) / 0.12); fout = smooth((e - t) / 0.10)
            sc = 0.94 + 0.06 * fin
            sp = spr if sc >= 0.999 else spr.resize((max(1, round(spr.width * sc)), max(1, round(spr.height * sc))), Image.BICUBIC)
            overlay(img, sp, W / 2 - sp.width / 2, CAP_Y - yc * sc + (1 - fin) * 10, min(fin, fout))
            break
    return img.convert("RGB").tobytes()

def overlay(img, spr, x, y, alpha):
    if alpha <= 0: return
    if alpha < 1:
        spr = spr.copy(); spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
    img.alpha_composite(spr, (int(round(x)), int(round(y))))

# ---------------------------------------------------------------- audio
def loudness(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r)[-1]), float(re.findall(r"Peak:\s+(-?[\d.inf]+) dBFS", r)[-1])

def duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout)

def ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)

def find(stem):
    m = sorted(glob.glob(A("assets", stem + ".wav"))) or sorted(glob.glob(A("assets", stem + ".*")))
    return m[0] if m else None

def build_audio(total, vo_offset):
    vo = find(f"{CFG['id']}_VO")
    bed = find(CFG["bed"]) if CFG.get("bed") else None
    vo_i, _ = loudness(vo)
    vo_n = A("build", "vo_norm.wav"); ms = int(round(vo_offset * 1000))
    ff("-i", vo, "-af", f"aformat=channel_layouts=stereo,adelay={ms}|{ms},volume={TARGET_LUFS - vo_i:.2f}dB,apad,atrim=0:{total:.3f}",
       "-ar", "48000", "-c:a", "pcm_f32le", vo_n)
    if bed:
        g = BED_LUFS - loudness(bed)[0]
        fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
        if duration(bed) < total + 0.5:  # extend with a long crossfade into a second pass (no audible seam)
            src = f"[1:a]{fmt}[b1];[2:a]{fmt}[b2];[b1][b2]acrossfade=d=8:c1=qsin:c2=qsin,"
            inputs = ["-i", bed, "-i", bed]
        else:
            src = f"[1:a]{fmt},"; inputs = ["-i", bed]
        graph = (src + f"atrim=0:{total:.3f},volume={g:.2f}dB,afade=t=in:d=1.5,afade=t=out:st={total - 2.5:.3f}:d=2.5[bed];"
                 "[0:a]asplit=2[vo][key];"
                 # duck under speech, bloom back in pauses and over the end card
                 "[bed][key]sidechaincompress=threshold=0.06:ratio=2:attack=150:release=1500:makeup=1[bedd];"
                 "[bedd]asplit=2[bedm][bedstem];[vo][bedm]amix=inputs=2:normalize=0:duration=first[mix]")
        mix = A("build", "mix.wav")
        ff("-i", vo_n, *inputs, "-filter_complex", graph, "-map", "[mix]", "-c:a", "pcm_f32le", mix,
           "-map", "[bedstem]", "-c:a", "pcm_f32le", A("build", "bed_stem.wav"))
    else:
        print("!! no music bed found in assets/ — building VO-only mix")
        mix = vo_n
    out = A("build", "master.wav"); gain = 0.0
    for _ in range(3):  # gain to target, brick-wall limit, correct once
        ff("-i", mix, "-af", f"volume={gain:.2f}dB,alimiter=limit={TP_LIMIT}:attack=3:release=60:level=false", "-c:a", "pcm_s24le", out)
        i, p = loudness(out)
        if abs(i - TARGET_LUFS) < 0.2: break
        gain += TARGET_LUFS - i
    print(f"master: {i:.1f} LUFS, peak {p:.1f} dBFS, bed={'yes' if bed else 'no'}")
    return out

# ---------------------------------------------------------------- main
def main():
    ep = sys.argv[1]; load_episode(ep)
    os.makedirs(A("build"), exist_ok=True); os.makedirs(A("out"), exist_ok=True)
    tl = timeline()
    if "--stills" in sys.argv:
        os.makedirs(A("build", "stills"), exist_ok=True)
        init_worker(ep)
        ts = [float(x) for x in sys.argv[sys.argv.index("--stills") + 1:]] or \
             [1, 3.3] + [(tl["win"][k][0] + tl["win"][k][1]) / 2 for k in tl["shots"]] + [tl["total"] - 0.1]
        for t in ts:
            Image.frombytes("RGB", (W, H), render(int(t * FPS))).save(A("build", "stills", f"t{t:07.2f}.jpg"), quality=90)
        print("stills ->", A("build", "stills")); return
    n = int(math.ceil(tl["total"] * FPS))
    print(f"total {tl['total']:.2f}s, {n} frames; shot windows:", {k: tuple(round(x, 2) for x in v) for k, v in tl["win"].items()})
    master = build_audio(n / FPS, tl["vo_offset"])
    out = A("out", f"{CFG['id']}_{CFG['slug']}.mp4")
    enc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-i", master, "-map", "0:v", "-map", "1:a",
                            "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-maxrate", "6M", "-bufsize", "12M", "-profile:v", "high", "-level", "4.2",
                            "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", "60",
                            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-shortest", "-movflags", "+faststart", out],
                           stdin=subprocess.PIPE)
    with Pool(os.cpu_count(), initializer=init_worker, initargs=(ep,)) as pool:
        for i, buf in enumerate(pool.imap(render, range(n), chunksize=8)):
            enc.stdin.write(buf)
            if i % 600 == 0: print(f"  frame {i}/{n}", flush=True)
    enc.stdin.close(); enc.wait()
    print("wrote", out)

if __name__ == "__main__":
    main()
