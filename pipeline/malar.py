"""
துலாமுள் — வாரமலர் (ஞாயிறு இணைப்பு, பக்கம் 17)

ஓட்டம் (ஞாயிறு அதிகாலை, run.py-லிருந்து):
  Claude → 10 பகுதி JSON → Gemini 10 ஓவியம் (5 சென்ற வாரம் + 5 நையாண்டி)
  → Pillow: ஒவ்வொன்றுக்கும் தமிழ் caption பொறிப்பு
  → அட்டைப்படம் + நூல் அட்டை + திரைப்பட போஸ்டர் (விக்கிமீடியா / TMDB / Open Library)
  → data/malar.json · data/malar/*.png
மனித வேலை இல்லை. படம் தோல்வியடைந்தாலும் உரை வெளியாகும்.
"""
import os, io, re, json, base64, time
from pathlib import Path
import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PIPE = ROOT / "pipeline"
DATA = ROOT / "data"
OUT = DATA / "malar"
FONT_DIR = PIPE / "fonts"

PAPER = (243, 242, 238); INK = (22, 27, 36); BRASS = (168, 134, 47); GREY = (140, 145, 155)
W = 1000                                  # ஓவியத்தின் அகலம்
UA = {"User-Agent": "Thulamul/1.0 (info@thulamul.com)"}


def _font(name, size):
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except Exception:
        return ImageFont.load_default()


def _wrap(d, text, font, max_w):
    out, cur = [], ""
    for w in str(text).split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


# ---------------------------------------------------------------- Gemini ஓவியம்
STYLE = ("Editorial ink-line illustration, black brush pen on warm off-white paper, "
         "cross-hatching for shade, single restrained brass-gold accent on one key object, "
         "clean composition, no colour wash, no photorealism. "
         "ABSOLUTELY NO TEXT: no words, letters, numbers, signage text or speech bubbles anywhere — "
         "every board, paper, screen and wall must be completely blank.")


def gemini_image(scene_en, tag=""):
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not scene_en:
        return None
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": STYLE + "\n\nSCENE: " + scene_en}]}],
                  "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
            timeout=120)
        for p in r.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])
    except Exception as ex:
        print(f"[malar:img{tag}] பிழை", str(ex)[:110])
    return None


def caption_image(img_bytes, caption_ta, kicker="", out_path=None):
    """ஓவியத்தின் கீழே தமிழ் caption பட்டை."""
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
    f_cap = _font("MeeraInimai-Regular.ttf", 30)
    f_kick = _font("NotoSerifTamil.ttf", 20)
    tmp = ImageDraw.Draw(im)
    pad = 30
    lines = _wrap(tmp, caption_ta, f_cap, W - 2 * pad)[:4]
    band = pad + (34 if kicker else 0) + len(lines) * 42 + pad
    out = Image.new("RGB", (W, im.height + band), PAPER)
    out.paste(im, (0, 0))
    d = ImageDraw.Draw(out)
    y = im.height + pad - 6
    d.line([(pad, im.height + 10), (W - pad, im.height + 10)], fill=BRASS, width=2)
    if kicker:
        d.text((pad, y), kicker, font=f_kick, fill=BRASS); y += 34
    for l in lines:
        d.text((pad, y), l, font=f_cap, fill=INK); y += 42
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        out.save(out_path, "PNG", optimize=True)
    return out_path


# ---------------------------------------------------------------- அட்டை / போஸ்டர்
def wiki_photo(q):
    """விக்கிப்பீடியா — நபர்/இடத்தின் CC படம்."""
    for lang in ("en", "ta"):
        try:
            r = requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                             + requests.utils.quote(str(q).replace(" ", "_")), headers=UA, timeout=15)
            if r.status_code != 200:
                continue
            d = r.json()
            src = (d.get("originalimage") or {}).get("source") or (d.get("thumbnail") or {}).get("source")
            if src:
                return {"url": src, "credit": f"விக்கிமீடியா · {d.get('title', q)}", "license": "CC"}
        except Exception:
            pass
    return None


def openlibrary_cover(q):
    """Open Library — நூல் அட்டை (மதிப்புரைக்காக)."""
    try:
        r = requests.get("https://openlibrary.org/search.json",
                         params={"q": q, "limit": 3, "fields": "cover_i,title"}, headers=UA, timeout=15).json()
        for doc in (r.get("docs") or []):
            cid = doc.get("cover_i")
            if cid:
                return {"url": f"https://covers.openlibrary.org/b/id/{cid}-L.jpg",
                        "credit": "Open Library", "license": "மதிப்புரைக்காக"}
    except Exception:
        pass
    return None


def tmdb_poster(q, year=None):
    """TMDB — திரைப்பட போஸ்டர் (விமர்சனத்திற்காக). TMDB_KEY இருந்தால்."""
    k = os.environ.get("TMDB_KEY")
    if not k:
        return None
    try:
        r = requests.get("https://api.themoviedb.org/3/search/movie",
                         params={"api_key": k, "query": q, "year": year}, headers=UA, timeout=15).json()
        for m in (r.get("results") or [])[:3]:
            p = m.get("poster_path")
            if p:
                return {"url": "https://image.tmdb.org/t/p/w500" + p,
                        "credit": "TMDB", "license": "விமர்சனத்திற்காக"}
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- build
def build(client, model, week, today, issue, dates_ta, kural_no, done_books, telegram=None):
    """run.py அழைக்கும். வெற்றி → dict; தோல்வி → None."""
    p = (PIPE / "prompts" / "malar.md").read_text(encoding="utf-8")
    p = (p.replace("{{WEEK}}", week).replace("{{TODAY}}", today).replace("{{ISSUE}}", str(issue))
          .replace("{{DATES}}", dates_ta).replace("{{KURAL_NO}}", str(kural_no))
          .replace("{{DONE_BOOKS}}", ", ".join(done_books[-30:]) or "(இல்லை)"))
    msg = client.messages.create(model=model, max_tokens=12000, system=p,
                                 messages=[{"role": "user", "content": f"{week} வாரமலரை எழுது. இதழ் {issue}."}])
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    m = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    m["week"] = week; m["issue"] = issue; m["generated"] = today; m["v"] = 3

    OUT.mkdir(parents=True, exist_ok=True)

    # அட்டைப்படம்
    m["cover"] = wiki_photo(m.get("cover_query", "")) or None

    # சென்ற வாரம் — 5 ஓவியம்
    for i, r in enumerate(m.get("roundup", [])[:5], 1):
        b = gemini_image(r.get("scene_en", ""), f"w{i}")
        if b:
            fp = OUT / f"{today}_week{i}.png"
            caption_image(b, r.get("text", ""), r.get("region", ""), fp)
            r["image"] = f"data/malar/{fp.name}"
        time.sleep(1)

    # நையாண்டி — 5 கேலிச்சித்திரம்
    for i, s in enumerate(m.get("satire", [])[:5], 1):
        b = gemini_image(s.get("scene_en", ""), f"s{i}")
        if b:
            fp = OUT / f"{today}_satire{i}.png"
            caption_image(b, s.get("line", ""), f"சாட்சி · {i}", fp)
            s["image"] = f"data/malar/{fp.name}"
        time.sleep(1)

    # நூல் அட்டை · திரைப்பட போஸ்டர்
    for b in m.get("books", []):
        b["cover"] = openlibrary_cover(b.get("cover_query") or b.get("title_en", "")) or None
    for f in m.get("films", []):
        f["poster"] = tmdb_poster(f.get("poster_query") or f.get("title", "")) or None

    if telegram:
        try:
            telegram(f"📔 <b>வாரமலர்</b> · இதழ் {issue}\n{m.get('essay', {}).get('title', '')}\n"
                     f"நூல்: {', '.join(b.get('title_ta', '') for b in m.get('books', []))}\n"
                     f"படம்: {', '.join(f.get('title', '') for f in m.get('films', []))}")
        except Exception:
            pass
    return m
