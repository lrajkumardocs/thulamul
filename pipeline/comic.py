"""
துலாமுள் — பொன்னியின் செல்வன் தினசரிக் காமிக்ஸ் (பக்கம் 18)

ஓட்டம் (தினமும் ஒரு முறை, run.py-லிருந்து):
  comic_state.json → இன்றைய arc/நாள் → Claude 4-பலகைக் கதை (JSON)
  → Gemini 4 படம் (பாத்திரக் குறிப்புப் படங்கள் உள்ளீடு; முந்தைய பலகையும் உள்ளீடு — ஒரே பாணி)
  → Pillow: 2×2 பக்கம், மேலே தலைப்பு, ஒவ்வொரு பலகையிலும் தமிழ் விவரிப்புப் பெட்டி + பேச்சுக் குமிழ்கள்
  → data/comic/YYYY-MM-DD.png · data/comic_index.json · data/comic_state.json → Telegram preview
Telegram-ல் "✘ comic" → இன்றையது மறையும்; நிலை பின்வாங்கும்; நாளை அதே நிகழ்வு மீண்டும்.
மனித வேலை இல்லை. பாதி வேலையில் தோல்வி → அடுத்த 30-நிமிட ஓட்டத்தில் மீதியைத் தொடரும் (comic_draft.json).
"""
import os, io, re, json, base64, textwrap, time
from datetime import datetime
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
DATA = ROOT / "data"
OUT = DATA / "comic"
REFS = PIPE / "comic_refs"
FONT_DIR = PIPE / "fonts"
STATE_FILE = DATA / "comic_state.json"
INDEX_FILE = DATA / "comic_index.json"
DRAFT_FILE = DATA / "comic_draft.json"

PAPER = (243, 242, 238); INK = (22, 27, 36); BRASS = (168, 134, 47); GREY = (140, 145, 155); WHITE = (255, 255, 255)
TA_M = ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"]

# பக்க வடிவம் — நிலையானது
W = 1080; MARGIN = 36; HEAD = 118; GUT = 22; FOOT = 84
PW = (W - 2 * MARGIN - GUT) // 2          # 500
PH = 560
H = MARGIN + HEAD + 2 * PH + GUT + FOOT + MARGIN

# ---------------------------------------------------------------- helpers
def _j(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default

def _save(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

def _font(name, size):
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except Exception:
        return ImageFont.load_default()

def _wrap(d, text, font, max_w):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def ta_date(today):
    d = datetime.strptime(today, "%Y-%m-%d")
    return f"{d.day} {TA_M[d.month - 1]} {d.year}"

CHARS = _j(PIPE / "comic_characters.json", {})
STORY = _j(PIPE / "comic_story.json", {})
CHAR_BY_ID = {c["id"]: c for c in CHARS.get("characters", [])}
BOOK_TA = {b["n"]: b["title_ta"] for b in STORY.get("books", [])}

# ---------------------------------------------------------------- state
def load_state():
    return _j(STATE_FILE, {"arc_i": 0, "day": 1, "global_day": 1, "story_so_far": "",
                           "arc_days": [], "last_date": None, "skip_date": None, "prev": None})

def current_arc(state):
    arcs = STORY.get("arcs", [])
    i = min(state.get("arc_i", 0), len(arcs) - 1)
    return i, arcs[i]

def advance(state, summary_ta, story_so_far):
    """இன்றையது வெளியானது → நாளைக்கு நிலை நகர்த்து. prev = பின்வாங்க."""
    snap = {k: v for k, v in state.items() if k != "prev"}
    state["prev"] = snap
    i, arc = current_arc(state)
    state["arc_days"] = (state.get("arc_days") or []) + [summary_ta]
    state["story_so_far"] = story_so_far or state.get("story_so_far", "")
    state["global_day"] = state.get("global_day", 1) + 1
    if state.get("day", 1) >= arc["days"] and i < len(STORY["arcs"]) - 1:
        state["arc_i"] = i + 1; state["day"] = 1; state["arc_days"] = []
    else:
        state["day"] = state.get("day", 1) + 1

def hide_today(today):
    """Telegram '✘ comic' — இன்றைய பக்கம் மறையும்; நிலை பின்வாங்கும்; இன்று மீண்டும் உருவாக்காது."""
    idx = _j(INDEX_FILE, [])
    for e in idx:
        if e["date"] == today:
            e["hidden"] = True
    _save(INDEX_FILE, idx)
    st = load_state()
    if st.get("last_date") == today and st.get("prev"):
        prev = st["prev"]; prev["prev"] = None
        prev["skip_date"] = today; prev["last_date"] = st["prev"].get("last_date")
        _save(STATE_FILE, prev)
    return True

# ---------------------------------------------------------------- 1. Claude — கதை
def write_script(client, model, state, today):
    i, arc = current_arc(state)
    sysm = (PIPE / "prompts/comic_day.md").read_text(encoding="utf-8")
    cast = "\n".join(f"- {c['id']}: {c['name_ta']} — {c['role_ta']}" for c in CHARS["characters"])
    extras = ", ".join(CHARS.get("extras_en", {}).keys())
    user = (f"ARC: பாகம் {arc['book']} «{BOOK_TA.get(arc['book'], '')}» · பகுதி «{arc['title_ta']}» · "
            f"N = {arc['days']} நாட்கள் · இன்று d = {state.get('day', 1)}\n"
            f"இடங்கள்: {arc.get('places', '')}\nஇப்பகுதியின் சுருக்கம்:\n{arc['synopsis_ta']}\n\n"
            f"STORY_SO_FAR:\n{state.get('story_so_far') or '(கதை இன்று தொடங்குகிறது — முதல் நாள்: கதையை அறிமுகம் செய்யும் விதமாகத் தொடங்கு)'}\n\n"
            f"ARC_DAYS_DONE:\n" + ("\n".join(f"{k + 1}. {s}" for k, s in enumerate(state.get('arc_days') or [])) or "(இல்லை)") +
            f"\n\nCAST (குறிப்புப் படம் உண்டு):\n{cast}\nஇப்பகுதியின் முக்கியப் பாத்திரங்கள்: {', '.join(arc.get('chars', []))}\n"
            f"extras (குறிப்புப் படம் இல்லை; scene_en-ல் விவரி): {extras}\n"
            f"இன்று: {today}. JSON மட்டும் தா.")
    msg = client.messages.create(model=model, max_tokens=3500, system=sysm, messages=[{"role": "user", "content": user}])
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    s = raw.find("{"); e = raw.rfind("}")
    script = json.loads(raw[s:e + 1])
    assert len(script["panels"]) == 4, "4 பலகை இல்லை"
    for p in script["panels"]:
        p.setdefault("bubbles", []); p.setdefault("caption_ta", ""); p.setdefault("characters", [])
        p["characters"] = [c for c in p["characters"] if c in CHAR_BY_ID][:3]
    return script

# ---------------------------------------------------------------- 2. Gemini — படம்
def _gemini(parts, tag):
    gk = os.environ.get("GEMINI_API_KEY")
    if not gk:
        print(f"[comic:{tag}] GEMINI_API_KEY இல்லை"); return None
    for model in ("gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation"):
        for attempt in (1, 2):
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": gk, "Content-Type": "application/json"},
                                  json={"contents": [{"parts": parts}],
                                        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}, timeout=180).json()
                if "error" in r:
                    print(f"[comic:{tag}] {model}:", str(r["error"].get("message", ""))[:120]); break
                for part in r.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                    data = part.get("inlineData") or part.get("inline_data")
                    if data and data.get("data"):
                        return base64.b64decode(data["data"])
                print(f"[comic:{tag}] {model}: படம் இல்லை (முயற்சி {attempt})")
            except Exception as ex:
                print(f"[comic:{tag}] {model} பிழை", str(ex)[:120])
    return None

def _img_part(b, mime="image/png"):
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(b).decode()}}

def draw_panel(panel, n, prev_bytes=None):
    """ஒரு பலகை. குறிப்புப் படங்கள் + முந்தைய பலகை → Gemini → bytes."""
    parts = [{"text": CHARS["style_en"] + "\n\nThis is one panel of a four-panel daily comic page. "
              "Portrait framing, roughly 7:8 (slightly taller than wide). Leave the upper part of the image comparatively calm and uncluttered (sky, plain wall, empty plaster) — a speech bubble will be added there later. "
              "Full colour in the fixed mural palette; ink outlines strong and clean."}]
    k = 0
    for cid in panel.get("characters", []):
        c = CHAR_BY_ID.get(cid); ref = REFS / f"{cid}.png"
        if not c:
            continue
        k += 1
        if ref.exists():
            parts.append({"text": f"Reference image {k}: this is '{c['name_en']}' ({cid}). Keep the face, hair, dress and colours exactly as shown."})
            parts.append(_img_part(ref.read_bytes()))
        else:
            parts.append({"text": f"Character '{c['name_en']}' ({cid}), no reference image — design: {c['visual_en']}"})
    for ex, desc in CHARS.get("extras_en", {}).items():
        if ex in (panel.get("scene_en", "") + " " + json.dumps(panel.get("bubbles", []))).lower():
            parts.append({"text": f"Minor character '{ex}': {desc}"})
    if prev_bytes:
        parts.append({"text": "The previous panel of this same page is shown next; match its style, palette, line weight and lighting exactly."})
        parts.append(_img_part(prev_bytes))
    parts.append({"text": f"NOW DRAW PANEL {n}: {panel['scene_en']}\nREMINDER: absolutely no text, letters, numbers or speech bubbles in the image."})
    return _gemini(parts, f"panel{n}")

# ---------------------------------------------------------------- 3. Pillow — பக்கம்
def _fit(b, w, h):
    im = Image.open(io.BytesIO(b)).convert("RGB")
    r = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * r)), max(h, int(im.height * r))), Image.LANCZOS)
    x = (im.width - w) // 2; y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))

def _rounded(d, box, r, fill, outline, width):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

def _bubble(d, panel_box, text, side, y, font, order):
    """பேச்சுக் குமிழ்: வெள்ளை, மை விளிம்பு, வால் பேசுபவரை நோக்கி. return next y."""
    x0, y0, x1, y1 = panel_box
    pad = 16; max_w = int((x1 - x0) * 0.62)
    lines = _wrap(d, text, font, max_w - 2 * pad)
    while len(lines) > 4 and font.size > 18:
        font = _font("MeeraInimai-Regular.ttf", font.size - 2); lines = _wrap(d, text, font, max_w - 2 * pad)
    lh = int(font.size * 1.45)
    bw = max(d.textlength(l, font=font) for l in lines) + 2 * pad
    bh = len(lines) * lh + 2 * pad - 6
    bx = x0 + 14 if side == "L" else x1 - 14 - bw
    if order == 1:                                   # இரண்டாவது குமிழ் சற்று உள்ளே
        bx = bx + 40 if side == "L" else bx - 40
    bx = max(x0 + 10, min(bx, x1 - 10 - bw))
    box = (bx, y, bx + bw, y + bh)
    _rounded(d, box, 18, WHITE, INK, 3)
    tx = bx + bw * (0.28 if side == "L" else 0.72)
    d.polygon([(tx - 12, y + bh - 2), (tx + 12, y + bh - 2), (tx + (-6 if side == "L" else 6), y + bh + 22)], fill=WHITE, outline=INK)
    d.line([(tx - 12, y + bh - 2), (tx + 12, y + bh - 2)], fill=WHITE, width=3)
    ty = y + pad - 4
    for l in lines:
        d.text((bx + pad, ty), l, font=font, fill=INK); ty += lh
    return y + bh + 26

def compose(panels_bytes, script, state, today, out_path):
    i, arc = current_arc(state)
    page = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(page)
    f_title = _font("NotoSerifTamil.ttf", 46); f_sub = _font("NotoSerifTamil.ttf", 21)
    f_cap = _font("NotoSerifTamil.ttf", 21); f_bub = _font("MeeraInimai-Regular.ttf", 26); f_foot = _font("NotoSerifTamil.ttf", 18)

    # தலைப்பு
    d.text((MARGIN, MARGIN - 6), "பொன்னியின் செல்வன்", font=f_title, fill=INK)
    sub = f"கல்கி · பாகம் {arc['book']} «{BOOK_TA.get(arc['book'], '')}» · {arc['title_ta']} · நாள் {state.get('global_day', 1)}"
    d.text((MARGIN, MARGIN + 60), sub, font=f_sub, fill=BRASS)
    t = script.get("title_ta", "")
    if t:
        d.text((W - MARGIN - d.textlength(t, font=f_sub), MARGIN + 60), t, font=f_sub, fill=GREY)
    d.line([(MARGIN, MARGIN + HEAD - 14), (W - MARGIN, MARGIN + HEAD - 14)], fill=INK, width=3)

    # 4 பலகை
    for n, (pb, p) in enumerate(zip(panels_bytes, script["panels"])):
        col, row = n % 2, n // 2
        x0 = MARGIN + col * (PW + GUT); y0 = MARGIN + HEAD + row * (PH + GUT)
        page.paste(_fit(pb, PW, PH), (x0, y0))
        d.rectangle((x0, y0, x0 + PW - 1, y0 + PH - 1), outline=INK, width=4)
        y = y0 + 12
        cap = (p.get("caption_ta") or "").strip()
        if cap:                                       # விவரிப்புப் பெட்டி — மேலே
            lines = _wrap(d, cap, f_cap, PW - 60)[:2]
            lh = int(f_cap.size * 1.5); bh = len(lines) * lh + 14
            d.rectangle((x0 + 12, y, x0 + PW - 12, y + bh), fill=PAPER, outline=INK, width=2)
            ty = y + 5
            for l in lines:
                d.text((x0 + 22, ty), l, font=f_cap, fill=INK); ty += lh
            y += bh + 14
        for k, b in enumerate((p.get("bubbles") or [])[:2]):
            txt = (b.get("text_ta") or "").strip()
            if txt:
                y = _bubble(d, (x0, y0, x0 + PW, y0 + PH), txt, "R" if str(b.get("side", "L")).upper().startswith("R") else "L", y, f_bub, k)
        d.text((x0 + PW - 30, y0 + PH - 30), str(n + 1), font=f_foot, fill=GREY)    # பலகை எண்

    # அடிக்குறிப்பு
    fy = H - MARGIN - FOOT + 22
    d.line([(MARGIN, fy - 12), (W - MARGIN, fy - 12)], fill=BRASS, width=2)
    d.text((MARGIN, fy), "துலாமுள் தினசரிக் காமிக்ஸ் · கல்கியின் நாவலின் ஓவிய வடிவம்", font=f_foot, fill=GREY)
    ds = ta_date(today); d.text((W - MARGIN - d.textlength(ds, font=f_foot), fy), ds, font=f_foot, fill=GREY)
    d.text((MARGIN, fy + 30), "நாளை தொடரும்...", font=f_foot, fill=INK)
    sig = FONT_DIR / "signature.png"
    if sig.exists():
        try:
            sg = Image.open(sig).convert("RGBA"); tw = 120
            sg = sg.resize((tw, max(1, int(sg.height * tw / sg.width))), Image.LANCZOS)
            page.paste(sg, (W - MARGIN - tw, fy + 24), sg)
        except Exception:
            pass
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    page.save(out_path, "PNG", optimize=True)
    return out_path

# ---------------------------------------------------------------- 4. telegram
def telegram_photo(path, caption):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    try:
        with open(path, "rb") as fh:
            requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto", data={"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                          files={"photo": fh}, timeout=60)
    except Exception as ex:
        print("[comic:telegram]", ex)

# ---------------------------------------------------------------- main entry
def build(client, model, today, telegram=None):
    """run.py அழைக்கும். இன்று ஏற்கெனவே வெளியானது / மறைக்கப்பட்டது எனில் ஒன்றும் செய்யாது."""
    state = load_state()
    if state.get("last_date") == today or state.get("skip_date") == today:
        return None
    if not STORY.get("arcs"):
        print("[comic] comic_story.json இல்லை"); return None
    OUT.mkdir(parents=True, exist_ok=True); wip = OUT / "_wip"; wip.mkdir(exist_ok=True)

    # 1. கதை — draft இருந்தால் மீண்டும் எழுதாது
    draft = _j(DRAFT_FILE, {})
    if draft.get("date") != today or not draft.get("script"):
        script = write_script(client, model, state, today)
        draft = {"date": today, "script": script}; _save(DRAFT_FILE, draft)
        for f in wip.glob("*.png"):
            f.unlink()
        print("[comic] கதை:", script.get("title_ta", ""))
    script = draft["script"]

    # 2. படங்கள் — தயாரானவை தவிர்த்து
    panels, prev = [], None
    for n, p in enumerate(script["panels"], 1):
        f = wip / f"{today}_{n}.png"
        b = f.read_bytes() if f.exists() else draw_panel(p, n, prev)
        if not b:
            print(f"[comic] பலகை {n} தோல்வி — அடுத்த ஓட்டத்தில் தொடரும்"); return None
        f.write_bytes(b); panels.append(b); prev = b
        print(f"[comic] பலகை {n} தயார்")

    # 3. பக்கம்
    out = OUT / f"{today}.png"
    compose(panels, script, state, today, out)
    for f in wip.glob("*.png"):
        f.unlink()

    # 4. index + state
    i, arc = current_arc(state)
    entry = {"date": today, "title": script.get("title_ta", ""), "book": arc["book"], "book_ta": BOOK_TA.get(arc["book"], ""),
             "arc": arc["title_ta"], "day": state.get("global_day", 1), "file": f"data/comic/{today}.png",
             "summary": script.get("summary_ta", ""), "hidden": False}
    idx = [e for e in _j(INDEX_FILE, []) if e["date"] != today]
    idx.insert(0, entry); _save(INDEX_FILE, idx)
    advance(state, script.get("summary_ta", ""), script.get("story_so_far_ta", ""))
    state["last_date"] = today; _save(STATE_FILE, state)
    _save(DRAFT_FILE, {})
    telegram_photo(out, f"📖 <b>பொன்னியின் செல்வன்</b> · நாள் {entry['day']} — {entry['title']}\n{entry['summary']}\n\nதவறு என்றால் <code>✘ comic</code>")
    print(f"[comic] பக்கம் தயார்: {out.name} · நாள் {entry['day']}")
    return entry

# ---------------------------------------------------------------- demo (API இல்லாமல் வடிவத்தைப் பார்க்க)
def _demo():
    import random
    script = {"title_ta": "ஆடித் திருநாள்", "panels": [
        {"caption_ta": "ஆடித் திருநாள். வீரநாராயண ஏரிக்கரை.", "bubbles": [{"side": "L", "text_ta": "இந்த ஏரியின் பரப்பு ஒரு கடல் போல!"}]},
        {"caption_ta": "", "bubbles": [{"side": "L", "text_ta": "அடே! கடம்பூர் மாளிகைக்கு வழி எது?"}, {"side": "R", "text_ta": "வழி சொல்கிறேன்; ஆனால் யார் நீ?"}]},
        {"caption_ta": "ஆழ்வார்க்கடியான் நம்பி — தடியும் நாமமும்.", "bubbles": [{"side": "R", "text_ta": "வைணவனுக்கு வழி கேட்டாய்; வாதமும் கிடைக்கும்!"}]},
        {"caption_ta": "", "bubbles": [{"side": "L", "text_ta": "இவன் யாரோ... சாதாரண பக்தன் அல்ல."}]}]}
    pb = []
    for n in range(4):
        im = Image.new("RGB", (700, 800), (232, 214, 176)); dd = ImageDraw.Draw(im)
        for _ in range(9):
            x, y = random.randint(40, 660), random.randint(300, 760)
            dd.ellipse((x - 60, y - 60, x + 60, y + 60), fill=random.choice([(184, 92, 52), (58, 74, 110), (120, 110, 60)]), outline=INK, width=5)
        bio = io.BytesIO(); im.save(bio, "PNG"); pb.append(bio.getvalue())
    st = load_state(); today = datetime.now().strftime("%Y-%m-%d")
    return compose(pb, script, st, today, OUT / "demo.png")

if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        print(_demo())
    elif "--hide" in sys.argv:
        hide_today(datetime.now().strftime("%Y-%m-%d"))
    else:
        from anthropic import Anthropic
        build(Anthropic(timeout=180, max_retries=2), os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"), datetime.now().strftime("%Y-%m-%d"))
