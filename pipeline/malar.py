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
STYLE_INK = ("Editorial ink-line illustration, black brush pen on warm off-white paper, "
         "cross-hatching for shade, single restrained brass-gold accent on one key object, "
         "clean composition, no colour wash, no photorealism. "
         "ABSOLUTELY NO TEXT: no words, letters, numbers, signage text or speech bubbles anywhere — "
         "every board, paper, screen and wall must be completely blank.")

STYLE_COLOUR = ("Rich colour editorial illustration, gouache and watercolour on textured paper, "
                "warm earthy palette with indigo, ochre, terracotta and deep green, soft light, "
                "visible brush texture, painterly — clearly a painting, never photorealistic. "
                "ABSOLUTELY NO TEXT: no words, letters, numbers, signage or speech bubbles anywhere — "
                "every board, paper, screen and wall must be completely blank.")


def gemini_image(scene_en, tag="", tries=2, style=None):
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not scene_en:
        return None
    for _n in range(tries):
        b = _gem_once(key, scene_en, tag, style or STYLE_COLOUR)
        if b:
            return b
        time.sleep(3)
    return None


def _gem_once(key, scene_en, tag, style):
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": style + "\n\nSCENE: " + scene_en}]}],
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
def build(client, model, week, today, issue, dates_ta, done_books, done_heroes, telegram=None):
    """run.py அழைக்கும். வெற்றி → dict; தோல்வி → None."""
    p = (PIPE / "prompts" / "malar.md").read_text(encoding="utf-8")
    p = (p.replace("{{WEEK}}", week).replace("{{TODAY}}", today).replace("{{ISSUE}}", str(issue))
          .replace("{{DATES}}", dates_ta)
          .replace("{{DONE_BOOKS}}", ", ".join(done_books[-30:]) or "(இல்லை)")
          .replace("{{DONE_HEROES}}", ", ".join(done_heroes[-40:]) or "(இல்லை)"))
    def _clean(raw):
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        i, j = raw.find("{"), raw.rfind("}")
        return raw[i:j + 1] if i >= 0 and j > i else raw

    def ask(part, budget, tries=2):
        last = ""
        for n in range(tries):
            mm = client.messages.create(model=model, max_tokens=budget, timeout=600.0, system=p,
                                        messages=[{"role": "user", "content": part}])
            raw = "".join(b.text for b in mm.content if getattr(b, "type", "") == "text").strip()
            last = raw
            try:
                return json.loads(_clean(raw))
            except Exception:
                if n == 0:
                    print("[malar] JSON மீள்முயற்சி")
                    part = part + "\n\nமுக்கியம்: JSON மட்டும் தா. விளக்கம், code fence, முன்னுரை எதுவும் வேண்டாம். { -இல் தொடங்கி } -இல் முடிய வேண்டும்."
                    time.sleep(2)
        # கடைசி முயற்சி — Claude-ஐயே சரிசெய்யச் சொல்
        try:
            fix = client.messages.create(model=model, max_tokens=budget, timeout=600.0,
                                         system="கீழே உள்ளதை செல்லுபடியாகும் JSON ஆக மட்டும் திருப்பித் தா. வேறு எதுவும் எழுதாதே.",
                                         messages=[{"role": "user", "content": last[:60000]}])
            return json.loads(_clean("".join(b.text for b in fix.content if getattr(b, "type", "") == "text")))
        except Exception as ex:
            raise RuntimeError("JSON தோல்வி: " + str(ex)[:100] + " | " + last[:200])

    # இரு பகுதியாக — ஒரே அழைப்பு நேரம் தாண்டுகிறது
    m = {}
    for part, budget in [
        ("cover_query, roundup, numbers", 6000),
        ("history, hero", 6000),
        ("essay, agri, spirit", 8000),
        ("word, zen, poem, food", 7000),
        ("books, films, remedy, satire", 9000),
    ]:
        try:
            m.update(ask(f"{week} வாரமலர், இதழ் {issue}. இந்தப் பகுதிகளை மட்டும் JSON-ஆகத் தா: "
                         f"{part}. மற்றவற்றை இப்போது தராதே.", budget))
        except Exception as ex:
            print(f"[malar] {part} தோல்வி:", str(ex)[:90])
        time.sleep(2)
    # விடுபட்டவற்றை மீண்டும் கேள் — முழு இதழ் உறுதி
    NEED = {"roundup": 5, "numbers": 5, "history": 7, "hero": 1, "essay": 1, "agri": 1,
            "spirit": 1, "word": 1, "zen": 1, "poem": 1, "food": 1, "books": 3,
            "films": 1, "remedy": 1, "satire": 5}
    for attempt in range(3):
        missing = [k for k, n in NEED.items()
                   if not m.get(k) or (isinstance(m.get(k), list) and len(m[k]) < min(n, 3))]
        if not missing:
            break
        print("[malar] விடுபட்டவை:", ", ".join(missing))
        for chunk in [missing[i:i + 3] for i in range(0, len(missing), 3)]:
            try:
                got = ask(f"{week} வாரமலர், இதழ் {issue}. இந்தப் பகுதிகளை மட்டும் JSON-ஆகத் தா: "
                          f"{', '.join(chunk)}. முழுமையாக, குறிப்பிட்ட எண்ணிக்கையுடன். மற்றவற்றை இப்போது தராதே.", 8000)
                for k in chunk:
                    if got.get(k):
                        m[k] = got[k]
            except Exception as ex:
                print(f"[malar] {chunk} மீள்முயற்சி தோல்வி:", str(ex)[:80])
            time.sleep(2)
    if not m:
        raise RuntimeError("எந்தப் பகுதியும் வரவில்லை")
    m["week"] = week; m["issue"] = issue; m["generated"] = today; m["v"] = 8

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
        b = gemini_image(s.get("scene_en", ""), f"s{i}", style=STYLE_INK)
        if b:
            fp = OUT / f"{today}_satire{i}.png"
            cap = (s.get("line") or "").strip()
            if not cap:
                cap = f"— {s.get('a','')}\n— {s.get('b','')}"
            caption_image(b, cap.replace("\n", "  "), f"நையாண்டி · {i}", fp)
            s["image"] = f"data/malar/{fp.name}"
        time.sleep(1)

    # கட்டுரை · ஜென் கதை — வண்ண ஓவியம்
    for key_, tag in (("essay", "essay"), ("zen", "zen")):
        blk = m.get(key_) or {}
        sc = blk.get("scene_en")
        if sc:
            b = gemini_image(sc, tag)
            if b:
                fp = OUT / f"{today}_{tag}.png"
                Path(fp).parent.mkdir(parents=True, exist_ok=True)
                im = Image.open(io.BytesIO(b)).convert("RGB")
                im = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
                im.save(fp, "PNG", optimize=True)
                blk["image"] = f"data/malar/{fp.name}"
            time.sleep(1)

    # பாட்டி — ஒரு முறை உருவாக்கி, எல்லா வாரமும் அதே
    gp = OUT / "granny.png"
    if not gp.exists():
        b = gemini_image("A kind smiling Tamil grandmother in a simple cotton saree, silver hair in a bun, "
                         "sitting beside a brass vessel and herbs, warm friendly expression, waist-up portrait",
                         "granny", style=STYLE_INK)
        if b:
            im = Image.open(io.BytesIO(b)).convert("RGB")
            im.thumbnail((600, 600), Image.LANCZOS)
            im.save(gp, "PNG", optimize=True)
    if gp.exists() and m.get("remedy"):
        m["remedy"]["image"] = "data/malar/granny.png"

    # மண்ணின் மைந்தர்கள் — உருவப்படம்
    hero = m.get("hero") or {}
    if hero:
        wi = wiki_photo(hero.get("name", ""))
        if wi:
            hero["photo"] = wi
        else:
            b = gemini_image(hero.get("scene_en", ""), "hero")
            if b:
                fp = OUT / f"{today}_hero.png"
                caption_image(b, hero.get("line", ""), hero.get("name", ""), fp)
                hero["image"] = f"data/malar/{fp.name}"

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
