"""
துலாமுள் — செய்தி இயந்திரம் (Session 1)
ஓட்டம்: மூலங்கள் (RSS) → புதியவை → ஒரே நிகழ்வு இணைப்பு → Claude 5-வரி → flag → ஆடியோ → data/ JSON

GitHub Actions ஒவ்வொரு 30 நிமிடமும் இதை ஓட்டும். மனிதன் தேவைப்படுவது flag ஆனவற்றுக்கு மட்டும் (Telegram).
"""
import os, re, json, hashlib, asyncio, time, socket
socket.setdefaulttimeout(20)   # எந்த இணைய அழைப்பும் 20 நொடிக்கு மேல் காத்திருக்காது
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

import yaml, feedparser, requests
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NEWS_DIR = DATA / "news"
AUDIO_DIR = DATA / "audio"
STATE_FILE = DATA / "state.json"          # பார்த்த items, published ids
FEED_FILE = DATA / "feed.json"            # ஆப் படிக்கும் ஒரே கோப்பு (கடைசி 200)
PENDING_FILE = DATA / "pending.json"      # flag ஆனவை — Telegram ஒப்புதல் காத்திருப்பு

IST = timezone(timedelta(hours=5, minutes=30))
TA_MONTHS = ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"]
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
MODEL_FAST = os.environ.get("CLAUDE_MODEL_FAST", "claude-haiku-4-5-20251001")
BIG_TOPICS = {"tn", "india", "assembly", "court", "economy"}
MAX_NEW_PER_RUN = int(os.environ.get("MAX_NEW_PER_RUN", "12"))    # ஒரு ஓட்டத்தில் அதிகபட்சம்
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "50"))
MIN_SCORE = int(os.environ.get("MIN_SCORE", "6"))               # இதற்குக் குறைவானவை எழுதப்படாது
TTS_VOICE = os.environ.get("TTS_VOICE", "ta-IN-PallaviNeural")   # Microsoft Edge இலவச தமிழ் குரல் (ஆண்: ta-IN-ValluvarNeural)
AUTO_PUBLISH_MIN_CONFIDENCE = 0.3

THIN = {"health", "agri", "jobs", "court", "spirit", "cinema", "sports", "tech"}   # தினமும் குறைந்தது 1 உறுதி
TOPIC_TA = {"tn": "தமிழ்நாடு", "india": "இந்தியா", "world": "உலகம்", "economy": "பொருளாதாரம்",
            "tech": "தொழில்நுட்பம்", "sports": "விளையாட்டு", "cinema": "சினிமா",
            "jobs": "வேலை · தேர்வு", "court": "நீதிமன்றம்", "assembly": "சட்டமன்றம்",
            "health": "சுகாதாரம்", "govt": "அரசு அறிவிப்புகள்", "crime": "சட்டம் ஒழுங்கு"}

# ---------------------------------------------------------------- helpers
def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

def clean_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()

def item_id(url):
    return hashlib.sha1(url.encode()).hexdigest()[:12]

def tokens(text):
    return set(w.lower() for w in re.findall(r"[A-Za-z\u0B80-\u0BFF0-9]{3,}", text))

# ---------------------------------------------------------------- 1. fetch
def fetch_all(sources, seen):
    """எல்லா RSS-ஐயும் படித்து, இதுவரை பார்க்காத items மட்டும் தரும்."""
    fresh = []
    for src in sources:
        try:
            r = requests.get(src["url"], headers={"User-Agent": "ThulamulBot/1.0"}, timeout=(10, 20))
            f = feedparser.parse(r.content)
            n = 0
            for e in f.entries[:30]:
                link = e.get("link") or ""
                if not link:
                    continue
                iid = item_id(link)
                if iid in seen:
                    continue
                pp = e.get("published_parsed") or e.get("updated_parsed")
                maxage = 72 if src.get("topic") in THIN else 36
                if pp and (time.time() - time.mktime(pp)) > maxage * 3600:
                    seen.add(iid); continue          # 36 மணிக்கு மேல் பழையது — தவிர்
                text = clean_html(e.get("summary") or e.get("description") or "")
                if hasattr(e, "content") and e.content:
                    text = clean_html(e.content[0].get("value", "")) or text
                img = None
                for m in (e.get("media_content") or []) + (e.get("media_thumbnail") or []):
                    if m.get("url"): img = m["url"]; break
                if not img:
                    for en in e.get("enclosures") or []:
                        if "image" in (en.get("type") or ""): img = en.get("href"); break
                if not img:
                    m = re.search(r'<img[^>]+src="([^"]+)"', (e.get("summary") or "") + "".join(c.get("value","") for c in getattr(e,"content",[]) or []))
                    if m: img = m.group(1)
                fresh.append({
                    "id": iid, "source": src["name"], "grade": src.get("grade", "media"), "img": img,
                    "topic_hint": src.get("topic"), "title": clean_html(e.get("title", "")),
                    "text": text[:4000], "link": link,
                    "published": e.get("published", "") or e.get("updated", ""),
                })
                n += 1
            print(f"[fetch] {src['name']}: {n} புதியவை")
        except Exception as ex:
            print(f"[fetch] {src['name']}: பிழை {ex}")
    return fresh

# ---------------------------------------------------------------- 2. cluster
def _stale(pub_str, days=3):
    """3 நாளுக்கு மேல் பழைய RSS உருப்படியா?"""
    if not pub_str:
        return False
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(str(pub_str))
        if d is None:
            return False
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).days > days
    except Exception:
        try:
            d = datetime.fromisoformat(str(pub_str).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - d).days > days
        except Exception:
            return False


def cluster(items, threshold=0.28):
    """ஒரே நிகழ்வைப் பற்றிய items-ஐ இணைக்கும் (தலைப்பு+உரை சொற்கள் Jaccard)."""
    clusters = []
    for it in items:
        if _stale(it.get("published")):
            continue                              # 3 நாளுக்கு மேல் பழையது
        t = tokens(it["title"] + " " + it["text"][:600])
        placed = False
        for c in clusters:
            if c["topic_hint"] != it["topic_hint"]:
                continue
            j = len(t & c["tokens"]) / max(1, len(t | c["tokens"]))
            if j >= threshold:
                c["items"].append(it); c["tokens"] |= t; placed = True; break
        if not placed:
            clusters.append({"topic_hint": it["topic_hint"], "tokens": t, "items": [it]})
    return clusters

# குற்றச்சாட்டு உள்ள செய்தி — இரு மூலம் கட்டாயம் (பிற துறைகளுக்கு நம்பகமான ஒரு ஊடகம் போதும்)
STRICT_TOPICS = {"crime"}

# நம்பகமான ஊடகங்கள் — ஒன்று போதும்
TRUSTED = ("hindu", "dinamalar", "dinamani", "indian express", "times of india", "ndtv",
           "pti", "ani", "business standard", "hindu tamil", "india today", "the print",
           "livemint", "economic times", "deccan", "news18", "maalaimalar", "daily thanthi",
           "vikatan", "puthiyathalaimurai", "polimer", "sun news", "bbc", "reuters", "afp")


def eligible(c):
    """வெளியீட்டுத் தகுதி.
    official ஒன்று போதும். media என்றால் 2 தனித்த மூலங்கள்.
    குற்றம்/நீதிமன்றம்/அரசு/பொருளாதாரம்/சுகாதாரம் — ஒரு மூலம் மட்டும் என்றால் **வெளியிடக் கூடாது**."""
    grades = {i["grade"] for i in c["items"]}
    names = {i["source"] for i in c["items"]}
    if "official" in grades:
        return True, []
    if len(names) >= 2:
        return True, []
    one = next(iter(names), "").lower()
    trusted = any(t in one for t in TRUSTED)
    if c.get("topic_hint") in STRICT_TOPICS and not trusted:
        return False, ["single_source_strict"]      # குற்றச் செய்தி + நம்பகமற்ற ஒரே மூலம்
    return True, ["single_source"]

# ---------------------------------------------------------------- 3. write (Claude)

FILLER_TOPICS = {
    "health": "பருவகால நோய், தடுப்பு, ஊட்டச்சத்து, சித்த/ஆயுர்வேத பொது அறிவு, அரசு சுகாதாரத் திட்டங்கள்",
    "world": "உலக அரசியல் அமைப்புகள் (ஐ.நா., உலக வங்கி), சர்வதேச ஒப்பந்தங்கள், உலக நாடுகளின் நிலவியல்-பொருளாதாரப் பின்னணி, இந்தியாவின் வெளியுறவு வரலாறு",
    "economy": "பொருளாதாரக் கருத்துகள் எளிய விளக்கம் — பணவீக்கம், ரெப்போ விகிதம், GST, பங்குச் சந்தை அடிப்படை, சேமிப்புத் திட்டங்கள், வரிக் கணக்கு",
    "court": "சட்ட அறிவு — அடிப்படை உரிமைகள், நுகர்வோர் சட்டம், RTI, தொழிலாளர் உரிமை, நீதிமன்ற நடைமுறை, இலவச சட்ட உதவி",
    "govt": "அரசுத் திட்டங்கள் விளக்கம் — யார் தகுதி, எப்படி விண்ணப்பிப்பது, என்ன ஆவணம், எங்கே செல்வது",
    "tech": "அன்றாடத் தொழில்நுட்பம் — UPI, ஆதார், இணைய பாதுகாப்பு, மோசடி தவிர்ப்பு, மொபைல் அமைப்புகள்",
    "sports": "தமிழ்நாட்டு விளையாட்டு மரபு — ஜல்லிக்கட்டு, சிலம்பம், கபடி, மல்யுத்தம்; விளையாட்டு வீரர் வரலாறு",
    "cinema": "தமிழ்த் திரைப்பட வரலாறு — முன்னோடிகள், தொழில்நுட்ப மாற்றங்கள், இசை மரபு, திரைத்துறை நடைமுறை",
    "india": "இந்திய அரசியலமைப்பு, நாடாளுமன்ற நடைமுறை, மாநில-மத்திய உறவு, தேசிய வரலாற்று நிகழ்வுகள்",
    "crime": "பொதுமக்கள் பாதுகாப்பு — சைபர் மோசடி தவிர்ப்பு, புகார் அளிக்கும் முறை, உதவி எண்கள், சட்ட உரிமைகள்",
    "jobs": "வேலைவாய்ப்புத் தயாரிப்பு — போட்டித் தேர்வு முறை, விண்ணப்ப நடைமுறை, நேர்காணல், திறன் மேம்பாடு",
}

def write_filler(client, topic, today, now):
    """செய்தி இல்லாத பக்கத்திற்கு ஒரு பொது அறிவுக் கட்டுரை (evergreen)."""
    sysmsg = (f"நீ துலாமுள் தமிழ் நாளிதழின் {TOPIC_TA.get(topic, topic)} பக்க எழுத்தாளர். இன்று இந்தப் பக்கத்தில் செய்தி குறைவு. "
              f"வாசகருக்குப் பயன்படும் ஒரு பொது அறிவுக் கட்டுரையை எழுது. பொருள்: {FILLER_TOPICS.get(topic,'')}. "
              "இது செய்தி அல்ல — நிலையான பயனுள்ள தகவல். உண்மைகள் மட்டும்; சந்தேகமான கூற்று வேண்டாம். "
              "மருத்துவ உத்தரவாதம், முதலீட்டு ஆலோசனை தராதே. "
              'JSON மட்டும், code fence இல்லை: {"headline":"தலைப்பு 6–12 சொல்","lines":["5 வாக்கியம் — ஒவ்வொன்றும் முற்றுப்புள்ளியில் முடிய வேண்டும்"],"closing":"ஒரு வரி முடிவு","tags":["2 சொல்"]}')
        
    try:
        msg = client.messages.create(model=MODEL, max_tokens=1500, system=cached(sysmsg),
                                     messages=[{"role": "user", "content": f"இன்று {today}. {TOPIC_TA.get(topic, topic)} பக்கத்திற்கு ஒரு கட்டுரை எழுது."}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        d = parse_json(client, raw)
        sid = f"art_{topic}_{today.replace('-','')}"
        story = {"id": sid, "headline": d["headline"], "lines": d.get("lines", [])[:5],
                 "closing": d.get("closing", ""), "closing_type": "background",
                 "sources": [{"name": "துலாமுள் தொகுப்பு", "doc": None, "date": today}],
                 "topic": topic, "topic_ta": TOPIC_TA.get(topic, topic), "entities": d.get("tags", []),
                 "confidence": 0.9, "flags": [], "front_cat": "routine", "urgent": False, "affected": "",
                 "kind": "article", "image": None, "status": "published",
                 "published_at": now.isoformat(timespec="minutes"), "created_ts": time.time()}
        story["audio"] = make_audio(sid, story["headline"] + ". " + " ".join(story["lines"]))
        return story
    except Exception as ex:
        print(f"[filler:{topic}] பிழை", str(ex)[:120])
        return None


# ---------------------------------------------------------------- சந்தை நிலவரம்
def _yf(sym):
    """Yahoo Finance — கடைசி விலை, முந்தைய இறுதி, சந்தை நேரம் (key இல்லை)."""
    for attempt in range(2):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"interval": "1d", "range": "10d"},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=20).json()
            res = r["chart"]["result"][0]
            meta = res.get("meta") or {}
            closes = [c for c in res["indicators"]["quote"][0]["close"] if c]
            if not closes:
                return None
            last = meta.get("regularMarketPrice") or closes[-1]
            # முந்தைய இறுதி — வரலாற்றுத் தொடரிலிருந்து (meta நம்பகமற்றது)
            prev = None
            for c in reversed(closes[:-1]):
                if c and abs(c - closes[-1]) / closes[-1] < 0.25:
                    prev = c
                    break
            if not prev:
                prev = meta.get("previousClose") or meta.get("chartPreviousClose") or last
            # last-ஐ closes[-1] உடன் ஒப்பிடு; regularMarketPrice வேறு நாளாக இருக்கலாம்
            if abs(last - closes[-1]) / closes[-1] > 0.25:
                last = closes[-1]
            ts = meta.get("regularMarketTime")
            return {"last": float(last), "prev": float(prev),
                    "ts": int(ts) if ts else None,
                    "state": meta.get("marketState", ""), "sym": sym}
        except Exception as ex:
            if attempt:
                print(f"[market:{sym}]", str(ex)[:80])
            time.sleep(2)
    return None


def _age_ta(ts):
    """எவ்வளவு நேரம் முன் — தமிழில்."""
    if not ts:
        return ""
    mins = int((time.time() - ts) / 60)
    if mins < 2:
        return "இப்போது"
    if mins < 60:
        return f"{mins} நிமிடம் முன்"
    if mins < 24 * 60:
        return f"{mins // 60} மணி நேரம் முன்"
    d = mins // (24 * 60)
    return "நேற்று" if d == 1 else f"{d} நாள் முன்"


def market_snapshot(prev_snap=None):
    """தங்கம், வெள்ளி, சென்செக்ஸ், நிஃப்டி, டாலர். திடீர் மாற்றம் என்றால் நிராகரிப்பு."""
    usdinr = _yf("INR=X"); gold = _yf("GC=F"); silver = _yf("SI=F")
    sensex = _yf("^BSESN"); nifty = _yf("^NSEI")
    if not usdinr:
        print("[market] டாலர் விகிதம் கிடைக்கவில்லை"); return None
    OZ = 31.1035
    GOLD_F, SILVER_F = 1.12, 1.22      # இந்திய இறக்குமதி வரி + GST
    old = prev_snap or {}
    out = {"at": datetime.now(IST).isoformat(timespec="minutes")}

    def sane(key, val, band=0.18):
        """முந்தைய மதிப்பிலிருந்து 10%-க்கு மேல் தாவினால் சந்தேகம் — பழையதை வை."""
        o = old.get(key)
        if o and val and abs(val - o) / o > band:
            print(f"[market] {key} சந்தேகமான மாற்றம் {o} → {round(val)} — பழையது வைக்கப்படுகிறது")
            return o, True
        return val, False

    def pct(d):
        if not d or not d.get("prev"):
            return 0.0
        v = round((d["last"] - d["prev"]) / d["prev"] * 100, 2)
        return 0.0 if abs(v) > 12 else v          # சந்தேகமான சதவீதம் — காட்டாதே

    if gold:
        g24 = gold["last"] * usdinr["last"] / OZ * GOLD_F
        g24, held = sane("gold24", round(g24))
        out["gold24"] = round(g24); out["gold22"] = round(g24 * 22 / 24)
        out["gold_pct"] = pct(gold)
        p24 = gold["prev"] * usdinr["last"] / OZ * GOLD_F
        out["gold24_chg"] = round(gold["last"] * usdinr["last"] / OZ * GOLD_F - p24)
        out["gold22_chg"] = round(out["gold24_chg"] * 22 / 24)
        out["gold_per10k"] = round(10000 / out["gold24"], 2)
        out["gold_age"] = _age_ta(gold.get("ts")); out["gold_ts"] = gold.get("ts")
        if held:
            out["gold_note"] = "சரிபார்ப்பில் உள்ளது"
    if silver:
        sv = silver["last"] * usdinr["last"] / OZ * SILVER_F
        sv, _ = sane("silver", round(sv, 2), 0.30)
        out["silver"] = round(sv, 2); out["silver_pct"] = pct(silver)
        out["silver_chg"] = round((silver["last"] - silver["prev"]) * usdinr["last"] / OZ * SILVER_F, 2)
    if sensex:
        v, _ = sane("sensex", round(sensex["last"]), 0.12)
        out["sensex"] = round(v); out["sensex_pct"] = pct(sensex)
        out["sensex_age"] = _age_ta(sensex.get("ts")); out["market_state"] = sensex.get("state", "")
    if nifty:
        v, _ = sane("nifty", round(nifty["last"]), 0.12)
        out["nifty"] = round(v); out["nifty_pct"] = pct(nifty)
    if usdinr:
        out["usd"] = round(usdinr["last"], 2); out["usd_pct"] = pct(usdinr)
        out["usd_age"] = _age_ta(usdinr.get("ts"))
    return out if out.get("gold24") or out.get("sensex") else None


def send_push(items, brief_item=None):
    """Firebase Cloud Messaging — பக்கம் வாரியாக அறிவிப்பு. FIREBASE_SA இல்லையெனில் தவிர்."""
    sa = os.environ.get("FIREBASE_SA")
    if not sa:
        return
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging, firestore as fs
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(json.loads(sa)))
        db = fs.client()
        subs = list(db.collection("push").stream())
        if not subs:
            return
        sent = 0
        for doc in subs:
            d = doc.to_dict() or {}
            topics = set(d.get("topics") or [])
            tok = d.get("token")
            if not tok or not topics:
                continue
            picks = []
            if brief_item and "front" in topics:
                picks.append(brief_item)
            for it in items:
                t = it.get("topic")
                if t in topics or ("front" in topics and it.get("front")):
                    picks.append(it)
            for p in picks[:2]:                      # ஒரு சாதனத்திற்கு ஓட்டத்திற்கு அதிகபட்சம் 2
                try:
                    messaging.send(messaging.Message(
                        data={"title": p["title"][:80], "body": p.get("body", "")[:140],
                              "url": p.get("url", "./"), "tag": p.get("tag", "thulamul")},
                        token=tok,
                        android=messaging.AndroidConfig(priority="high"),
                    ))
                    sent += 1
                except Exception as ex:
                    if "not-registered" in str(ex) or "invalid" in str(ex).lower():
                        doc.reference.delete()       # செல்லாத token நீக்கு
        print(f"[push] {sent} அறிவிப்புகள்")
    except Exception as ex:
        print("[push] பிழை", str(ex)[:150])

def make_cartoon(scene_en, today, caption=""):
    """Gemini மூலம் கேலிச்சித்திரம் + கீழே தமிழ் வசனப் பட்டை. தோல்வி → None."""
    gk = os.environ.get("GEMINI_API_KEY")
    if not gk or not scene_en:
        print("[cartoon] key/scene இல்லை"); return None
    style = (
        "A single-panel editorial cartoon for a Tamil newspaper. Landscape 4:3 composition, wide frame.\n"
        "STYLE: hand-drawn black ink brush-pen line art with fine cross-hatching, on warm off-white paper (#F3F2EE). "
        "Monochrome throughout EXCEPT one single small accent in muted antique brass-gold (#A8862F) on the most important object in the scene. "
        "Expressive but dignified faces; no caricature of any real person.\n"
        "CRITICAL — ZERO TEXT: the image must contain no writing of any kind. No words, no letters (Latin, Tamil or any script), no numbers, no captions, no labels, no logos, no speech bubbles, no handwriting. "
        "Every board, sign, poster, banner, file, paper, screen, badge and wall must be COMPLETELY BLANK — empty surfaces only. Do not attempt to render Tamil or English text anywhere; leave those surfaces plain. "
        "If a sign is needed for the gag, draw an empty frame.\n"
        "RECURRING CHARACTER (must appear, always the same): 'Saatchi' — a thin, calm, middle-aged Tamil man, short grey-flecked hair, "
        "plain white veshti and white half-sleeve shirt, a folded white towel over his left shoulder, a folded newspaper in his right hand, "
        "standing quietly at the right edge of the frame, not participating, simply observing the scene with a level gaze.\n"
        "CONTENT RULES: satirise the situation, never a person or party; no real politicians, no identifiable public figures, no religious symbols, "
        "no violence, no caste or communal markers. Indian/Tamil Nadu setting, ordinary people.\n"
        "COMPOSITION: the bottom-left corner (about 25% width x 15% height) must be completely blank plain paper — absolutely no figures, no hatching, no marks, no scribbles there. That space is reserved.\n"
        "SCENE: ")
    import base64
    for model in ("gemini-2.5-flash-image", "gemini-2.0-flash-preview-image-generation"):
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": gk, "Content-Type": "application/json"},
                              json={"contents": [{"parts": [{"text": style + scene_en}]}],
                                    "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}, timeout=150).json()
            if "error" in r:
                print(f"[cartoon] {model}:", str(r["error"].get("message", ""))[:120]); continue
            for part in r.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                data = part.get("inlineData") or part.get("inline_data")
                if data and data.get("data"):
                    (DATA / "cartoons").mkdir(parents=True, exist_ok=True)
                    fn = DATA / "cartoons" / f"{today}.png"
                    fn.write_bytes(base64.b64decode(data["data"]))
                    if caption:
                        try:
                            import importlib, sys
                            sys.path.insert(0, str(ROOT / "pipeline"))
                            cap = importlib.import_module("caption")
                            d = datetime.strptime(today, "%Y-%m-%d")
                            TA_M = ["ஜனவரி","பிப்ரவரி","மார்ச்","ஏப்ரல்","மே","ஜூன்","ஜூலை","ஆகஸ்ட்","செப்டம்பர்","அக்டோபர்","நவம்பர்","டிசம்பர்"]
                            cap.add_caption(fn, caption, f"{d.day} {TA_M[d.month-1]} {d.year}")
                        except Exception as ex:
                            print("[caption] பிழை", str(ex)[:100])
                    print(f"[cartoon] {model}: படம் தயார்")
                    return f"data/cartoons/{today}.png"
            print(f"[cartoon] {model}: படம் திரும்பவில்லை")
        except Exception as ex:
            print(f"[cartoon] {model} பிழை", str(ex)[:120])
    return None


def cached(text):
    """System prompt-ஐ cache செய் — மீண்டும் அனுப்பும்போது 90% மலிவு.
    1024 token-க்கு மேல் உள்ள prompt-களுக்கு மட்டும் பயனுள்ளது."""
    t = str(text or "")
    if len(t) < 3000:                      # சிறியது — cache தேவையில்லை
        return t
    return [{"type": "text", "text": t, "cache_control": {"type": "ephemeral"}}]

def parse_json(client, raw, what="JSON"):
    """JSON-ஐ படிக்க முயல்; தோல்வி → Claude-ஐயே திருத்தச் சொல் (சிறிய அழைப்பு)."""
    a, b = raw.find("{"), raw.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(raw[a:b + 1])
        except Exception:
            pass
    fix = client.messages.create(model=MODEL, max_tokens=4000, system="You repair broken JSON. Return ONLY valid JSON, no prose, no code fences. Keep all text content exactly; escape quotes/newlines inside strings; close any truncated structure sensibly.",
                                 messages=[{"role": "user", "content": raw[:12000]}])
    r2 = "".join(x.text for x in fix.content if getattr(x, "type", "") == "text")
    a, b = r2.find("{"), r2.rfind("}")
    return json.loads(r2[a:b + 1])


def triage(client, clusters):
    """எழுதுவதற்கு முன் தரம் பார்ப்பு — Haiku ஒரே அழைப்பில் எல்லாத் தலைப்புகளுக்கும் 1–10 மதிப்பெண்.
    முக்கியமானவை மட்டும் எழுதப்படும்; சாதாரணமானவை தவிர்க்கப்படும்."""
    if not clusters:
        return {}
    items = []
    for n, c in enumerate(clusters[:120]):
        t = c["items"][0]
        items.append(f"{n}. [{TOPIC_TA.get(c['topic_hint'], c['topic_hint'])}] {t['title'][:150]}")
    sysmsg = ("நீ தமிழ் நாளிதழின் செய்தி ஆசிரியர். கீழே இன்றைய நிகழ்வுத் தலைப்புகள். ஒவ்வொன்றுக்கும் "
              "'இது நாளிதழில் இடம்பெற வேண்டுமா' என்று 1–10 மதிப்பெண் தா.\n"
              "10–9 = உயிரிழப்பு, பேரிடர், தாக்குதல், தலைவர் மரணம்/கைது, தேர்தல், போர்.\n"
              "8–7 = முதல்வர்/பிரதமர் அறிவிப்பு, சட்டமன்றம், நீதிமன்றத் தீர்ப்பு, விலை/வட்டி/வரி, பெரும் திட்டம், ஊழல், சுகாதார எச்சரிக்கை.\n"
              "6–5 = துறை அறிவிப்பு, மாவட்டத் திட்டம், வேலைவாய்ப்பு, முக்கிய வழக்கு, பெரிய விளையாட்டு/சினிமா நிகழ்வு.\n"
              "4–1 = வழக்கமான கூட்டம், அறிக்கை, சந்தை ஏற்ற இறக்கம், தயாரிப்பு அறிவிப்பு, பட்டியல்/கருத்துக் கட்டுரை, வெளிநாட்டு உள்ளூர்ச் செய்தி, விளம்பரம் போன்றவை.\n"
              "தமிழ்நாடு தொடர்பானதற்கு ஒரு புள்ளி கூடுதல். "
              "கண்டிப்பாக: பெரும்பாலான தலைப்புகள் 3–4 மதிப்பெண் பெற வேண்டும். 6-க்கு மேல் தருவது ஒரு நாளிதழின் "
              "பக்கத்தில் இடம்பெறத் தகுதியான, மக்களைப் பாதிக்கும் செய்திகளுக்கு மட்டும் — 100-ல் 15-க்கு மேல் இருக்கக் கூடாது. "
              'JSON மட்டும், code fence இல்லை: {"s":{"0":7,"1":3,...}} — எண் மட்டும்.')
    try:
        msg = client.messages.create(model=MODEL_FAST, max_tokens=2000, system=cached(sysmsg),
                                     messages=[{"role": "user", "content": "\n".join(items)}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("s", {})
        return {int(k): int(v) for k, v in d.items()}
    except Exception as ex:
        print("[triage] பிழை", str(ex)[:120])
        return {}

def write_news(client, prompt, c, today, model=None):
    src_text = "\n\n".join(
        f"[மூலம் {n+1}: {i['source']}]\nதலைப்பு: {i['title']}\n{i['text'][:800]}"
        for n, i in enumerate(c["items"][:2]))
    msg = client.messages.create(
        model=(model or MODEL), max_tokens=3000,
        system=cached(prompt.replace("{{TODAY}}", today)),
        messages=[{"role": "user", "content": f"துறை குறிப்பு: {c['topic_hint']}\n\n{src_text}"}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    return parse_json(client, raw)


# ---------------------------------------------------------------- உரைத் தரக் காவல்
# அனுமதிக்கப்பட்டவை: தமிழ் · ஆங்கிலம் · எண் · நிறுத்தற்குறி · இடைவெளி · ₹ % ° — வேறு எதுவும் பிழை
ALLOWED = re.compile(r"[\u0B80-\u0BFFa-zA-Z0-9\s.,;:!?'\"()\[\]{}\-–—/%₹°+*=<>@&#_|\\~`^$…‘’“”\u200b\u200c\u200d\u00b7\u00a0\u2013\u2014\u2018\u2019\u201c\u201d\u2026\u20b9\u00b0\u00bd\u00bc]")


def foreign_chars(text):
    """தமிழ்/ஆங்கிலம் அல்லாத எழுத்துகள் (இந்தி, வங்காளம், சீனம், கொரியம்…) பட்டியல்."""
    return sorted({ch for ch in str(text or "") if not ALLOWED.match(ch)})
BAD_TAIL = ("மற்றும்", "ஆனால்", "என்று", "என", "இதனால்", "அதனால்", "எனவே", "-", "–", "…", ",", ";", ":")



# ---------------------------------------------------------------- உண்மைச் சரிபார்ப்பு
TA_NUM = {"ஒன்று": "1", "இரண்டு": "2", "மூன்று": "3", "நான்கு": "4", "ஐந்து": "5", "ஆறு": "6",
          "ஏழு": "7", "எட்டு": "8", "ஒன்பது": "9", "பத்து": "10", "நூறு": "100", "ஆயிரம்": "1000"}


def _nums(text):
    """உரையில் உள்ள எண்கள் — காற்புள்ளி/இடைவெளி நீக்கி ஒப்பிடத் தயார்."""
    out = set()
    for m in re.finditer(r"\d[\d,\.]*", str(text or "")):
        t = m.group(0).rstrip(".").replace(",", "")
        if t:
            out.add(t)
            if "." in t:
                out.add(t.split(".")[0])
    return out


def fact_problems(story, src_text):
    """மூலத்தில் இல்லாத எண் / ஆண்டு செய்தியில் வந்தால் பிழை. தவறான தகவலைத் தடுக்கும்."""
    src = _nums(src_text)
    # ஆண்டுகளும் சதவீதமும் மூலத்தில் இருக்க வேண்டும்
    body = " ".join([str(story.get("headline") or "")] + [str(x) for x in (story.get("lines") or [])])
    bad = []
    for n in _nums(body):
        if n in src:
            continue
        # சிறிய எண்கள் (1–12) பொதுவான சொற்களில் வரலாம் — தவிர்
        try:
            if len(n) <= 2 and int(float(n)) <= 12:
                continue
        except Exception:
            pass
        # 2.5 → 2.50, 1240 → 1,240 வடிவ வேறுபாடு
        alt = {n.lstrip("0"), n + "0", n.rstrip("0").rstrip(".")}
        if alt & src:
            continue
        bad.append(n)
    return ["மூலத்தில் இல்லாத எண்: " + ", ".join(bad[:5])] if bad else []


# ---------------------------------------------------------------- தமிழ் எழுத்துப் பிழை
COMMON_TA = {
    "காஞ்சிபுரம்", "திருவள்ளூர்", "செங்கல்பட்டு", "கள்ளக்குறிச்சி", "திருவண்ணாமலை",
    "விழுப்புரம்", "மயிலாடுதுறை", "நாகப்பட்டினம்", "திருவாரூர்", "புதுக்கோட்டை",
    "திருச்சிராப்பள்ளி", "கிருஷ்ணகிரி", "தருமபுரி", "கோயம்புத்தூர்", "திண்டுக்கல்",
    "ராமநாதபுரம்", "விருதுநகர்", "தூத்துக்குடி", "திருநெல்வேலி", "கன்னியாகுமரி",
    "அரியலூர்", "பெரம்பலூர்", "நாமக்கல்", "சிவகங்கை", "தென்காசி", "திருப்பத்தூர்",
    "ராணிப்பேட்டை", "திருப்பூர்", "நீலகிரி", "வேலூர்", "கடலூர்", "தஞ்சாவூர்", "மதுரை",
    "சேலம்", "ஈரோடு", "கரூர்", "தேனி", "சென்னை", "துருவ", "வன்னி", "முதலமைச்சர்",
    "அமைச்சர்", "நீதிமன்றம்", "உயர்நீதிமன்றம்", "சட்டமன்றம்", "ஆணையம்", "நட்சத்திரம்",
}


def _ed1(a, b, lim=2):
    """திருத்த தூரம் lim-க்குள் இருக்கிறதா?"""
    if abs(len(a) - len(b)) > lim:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
        if min(prev) > lim:
            return False
    return prev[-1] <= lim


SUFFIX = ("ுக்கு", "ில்", "ின்", "ால்", "ாக", "ஆக", "ையும்", "ையே", "ை", "ும்", "ே", "ா",
          "த்தில்", "த்தின்", "த்தை", "த்துக்கு", "கள்", "களில்", "களுக்கு", "வில்", "வின்")

# அறியப்பட்ட எழுத்துக் குழப்பங்கள் (ண/ன, ழ/ள, ற/ர) — நேரடித் திருத்தம்
FIX_MAP = {
    "வண்ணை": "வன்னி", "கஞ்சிபுரம்": "காஞ்சிபுரம்", "தருவ": "துருவ",
    "கோயம்பத்தூர்": "கோயம்புத்தூர்", "திருச்சிராபள்ளி": "திருச்சிராப்பள்ளி",
    "தூத்துகுடி": "தூத்துக்குடி", "நாகபட்டினம்": "நாகப்பட்டினம்",
    "விழுபுரம்": "விழுப்புரம்", "கன்னியகுமரி": "கன்னியாகுமரி",
    "திருநெல்வேளி": "திருநெல்வேலி", "செங்கல்பட்டு": "செங்கல்பட்டு",
}


def _stem(w):
    for suf in sorted(SUFFIX, key=len, reverse=True):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)]
    return w


def spell_fix(story, src_text):
    """செய்தியில் உள்ள தமிழ்ச் சொல் மூலத்தில் இல்லை, ஆனால் மூலத்தில் ஒத்த சொல் இருந்தால் — திருத்து.
    வண்ணை → வன்னி, தருவ → துருவ, கஞ்சிபுரம் → காஞ்சிபுரம்."""
    src_words = set(re.findall(r"[\u0B80-\u0BFF]{3,}", str(src_text or "")))
    known = src_words | COMMON_TA
    stems = {_stem(k) for k in known}
    fixes = {}
    for field in ("headline", "closing"):
        pass
    body = [str(story.get("headline") or "")] + [str(x) for x in (story.get("lines") or [])] + [str(story.get("closing") or "")]
    for txt in body:
        for w in re.findall(r"[\u0B80-\u0BFF]{4,}", txt):
            if w in fixes:
                continue
            if w in FIX_MAP:
                fixes[w] = FIX_MAP[w]
                continue
            if w in known or _stem(w) in stems:
                continue
            cand = [k for k in known if _ed1(w, k, 2) and abs(len(k) - len(w)) <= 1
                    and k[:1] == w[:1] and k[-1:] == w[-1:]]
            # ஒரே ஒரு பொருத்தம் இருந்தால் மட்டும் திருத்து (தெளிவற்றால் விடு)
            if len(cand) == 1:
                fixes[w] = cand[0]
    if not fixes:
        return story, []
    def apply(t):
        for a, b in fixes.items():
            t = t.replace(a, b)
        return t
    story["headline"] = apply(str(story.get("headline") or ""))
    story["lines"] = [apply(str(x)) for x in (story.get("lines") or [])]
    if story.get("closing"):
        story["closing"] = apply(str(story["closing"]))
    return story, [f"{a}→{b}" for a, b in list(fixes.items())[:4]]

def text_problems(story):
    """வெளியிடுவதற்கு முன் கட்டாயச் சோதனை. பிழைப் பட்டியலைத் திருப்பும்; காலி = சரி."""
    errs = []
    head = str(story.get("headline") or "").strip()
    lines = [str(x).strip() for x in (story.get("lines") or [])]
    closing = str(story.get("closing") or "").strip()
    blob = " ".join([head] + lines + [closing])

    fc = foreign_chars(blob)
    if fc:
        errs.append("தமிழ் அல்லாத எழுத்து: " + "".join(fc[:8]))
    if len(head) < 12:
        errs.append("தலைப்பு மிகக் குறுகியது")
    if head.endswith(BAD_TAIL):
        errs.append("தலைப்பு முழுமையடையவில்லை")
    if len(lines) < 4:
        errs.append("வரிகள் போதவில்லை")
    for i, l in enumerate(lines, 1):
        if len(l) < 25:
            errs.append(f"வரி {i} மிகக் குறுகியது")
        if not l.endswith((".", "?", "!")):
            errs.append(f"வரி {i} முற்றுப்புள்ளி இல்லை")
        if l.rstrip(".?!").rstrip().endswith(BAD_TAIL):
            errs.append(f"வரி {i} அரைகுறையாக முடிகிறது")
        if l.count("(") != l.count(")"):
            errs.append(f"வரி {i} அடைப்புக்குறி பொருந்தவில்லை")
    if closing and not closing.endswith((".", "?", "!")):
        errs.append("முடிவு வரி முற்றுப்புள்ளி இல்லை")
    # ஒரே வரி மீண்டும்
    if len(set(lines)) < len(lines):
        errs.append("வரி மீண்டும் வருகிறது")
    return errs




def _hwords(t):
    return {w for w in re.findall(r"[\u0B80-\u0BFF]{4,}", str(t or ""))}


def is_duplicate(story, feed, today):
    """இன்று ஏற்கனவே வெளியான செய்தியுடன் ஒத்திருக்கிறதா — தலைப்புச் சொல் ஒப்பீடு."""
    new = _hwords(story.get("headline"))
    if len(new) < 3:
        return False
    for x in feed:
        if str(x.get("published_at", ""))[:10] != today or x.get("status") != "published":
            continue
        old = _hwords(x.get("headline"))
        if not old:
            continue
        j = len(new & old) / max(1, len(new | old))
        if j >= 0.35:
            return x.get("headline", "")[:60]
    return False


def dedupe_feed(feed, today):
    """சேமிப்பதற்கு முன் இறுதிச் சுத்தம் — ஒரே நாளில் ஒத்த தலைப்புகள் இருந்தால் முதலியது மட்டும்."""
    kept, dropped = [], 0
    todays = []
    for x in feed:
        if str(x.get("published_at", ""))[:10] != today or x.get("status") != "published":
            kept.append(x); continue
        a = _hwords(x.get("headline"))
        dup = False
        for y in todays:
            b = _hwords(y.get("headline"))
            if not a or not b:
                continue
            if len(a & b) / max(1, len(a | b)) >= 0.35:
                dup = True; break
        if dup:
            dropped += 1
            continue
        todays.append(x); kept.append(x)
    if dropped:
        print(f"[நகல்] {dropped} மீண்டும் வந்த செய்தி நீக்கப்பட்டது")
    return kept

def proofread(client, story, src_text):
    """கட்டாயப் பிழைதிருத்தம் — Haiku (மலிவு). சூழல் பிழைகளைப் பிடிக்கும்:
    'தேதி→தேனி', 'வேட்டுவம்→வெட்டுவம்' போன்ற சரியான-சொல் தவறுகள்."""
    sysmsg = (
        "நீ தமிழ்ச் செய்தித்தாளின் பிழைதிருத்துநர். கீழே ஒரு செய்தி JSON மற்றும் அதன் மூல உரை.\n"
        "**மூல உரையை ஒப்பிட்டு** செய்தியில் உள்ள பிழைகளைத் திருத்து:\n"
        "1. எழுத்துப் பிழை — ண/ன, ழ/ள/ல, ற/ர, ஒற்று மிகுதல்/குறைதல்.\n"
        "2. **சூழல் பிழை — மிக முக்கியம்.** சரியான தமிழ்ச் சொல்லே தவறான இடத்தில் வந்திருக்கலாம். "
        "இவற்றைக் கவனமாகப் பார்: தேதி↔தேனி · வங்கி↔வன்னி · வட்டி↔வன்னி · வேட்டுவம்↔வெட்டுவம் · "
        "காஞ்சிபுரம்↔கஞ்சிபுரம் · துருவ↔தருவ · சட்டமன்றம்↔சட்டமன்றத் · நூற்றுக்கு↔நூற்றிற்கு. "
        "**மூல உரையில் உள்ள சொல்லே சரி** — ஒவ்வொரு பெயர்ச்சொல்லையும் மூலத்துடன் ஒப்பிடு.\n"
        "   வங்கி = bank; வன்னி = ஒரு மரம்/இடப்பெயர். தேதி = date; தேனி = மாவட்டம். குழப்பாதே.\n"
        "3. பெயர்ச்சொற்கள் — நபர், ஊர், அமைப்பு, படம், திட்டம் — **மூல உரையில் உள்ளபடியே** இருக்க வேண்டும்.\n"
        "4. முழுமையடையாத வாக்கியம், விடுபட்ட சொல், இரட்டைச் சொல்.\n"
        "5. மரியாதைப் பன்மை — நபரைக் குறிக்கும்போது 'அவர்/வந்தார்'.\n"
        "பொருளை மாற்றாதே; புதிய தகவல் சேர்க்காதே; எண்களைத் தொடாதே.\n"
        "திருத்தப்பட்ட JSON-ஐ மட்டும் திருப்பித் தா: {\"headline\":\"\",\"lines\":[],\"closing\":\"\"} — "
        "code fence இல்லை, விளக்கம் இல்லை. பிழை இல்லையென்றால் அதையே திருப்பித் தா.")
    payload = json.dumps({"headline": story.get("headline"), "lines": story.get("lines"),
                          "closing": story.get("closing")}, ensure_ascii=False)
    msg = client.messages.create(
        model=MODEL_FAST, max_tokens=1500, system=cached(sysmsg),
        messages=[{"role": "user", "content": "மூல உரை:\n" + str(src_text)[:1800] +
                                              "\n\nசெய்தி:\n" + payload}])
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    d = parse_json(client, raw)
    out = dict(story)
    for k in ("headline", "lines", "closing"):
        v = d.get(k)
        if v and (not isinstance(v, list) or len(v) == len(story.get("lines") or [])):
            out[k] = v
    return out

def fix_text(client, story, errs):
    """பிழைகளைச் சொல்லி Claude-ஐத் திருத்தச் சொல்."""
    sysmsg = ("நீ தமிழ்ச் செய்தி ஆசிரியர். கீழே ஒரு செய்தி JSON மற்றும் அதில் உள்ள பிழைகள். "
              "பிழைகளைத் திருத்திய அதே JSON-ஐத் திருப்பித் தா — headline, lines, closing மட்டும் மாற்று; "
              "மற்ற புலங்களை அப்படியே வை. விதிகள்: முழுவதும் தமிழ் எழுத்து (இந்தி/தெலுங்கு/கன்னடம் கூடாது; "
              "பெயர்களைத் தமிழில் ஒலிபெயர்); ஒவ்வொரு வரியும் முழுமையான வாக்கியம், முற்றுப்புள்ளியில் முடிய வேண்டும்; "
              "ஒரு வரி 20 சொல்லுக்குள்; அரைகுறையாக முடியக் கூடாது. JSON மட்டும், code fence இல்லை.")
    payload = json.dumps({"headline": story.get("headline"), "lines": story.get("lines"),
                          "closing": story.get("closing")}, ensure_ascii=False)
    msg = client.messages.create(model=MODEL, max_tokens=2500, system=cached(sysmsg),
                                 messages=[{"role": "user", "content": payload + "\n\nபிழைகள்: " + "; ".join(errs)}])
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    d = parse_json(client, raw)
    for k in ("headline", "lines", "closing"):
        if d.get(k):
            story[k] = d[k]
    return story

def validate(story):
    ok = isinstance(story.get("lines"), list) and len(story["lines"]) == 5
    ok &= bool(story.get("headline")) and bool(story.get("closing"))
    ok &= story.get("topic") in TOPIC_TA
    return ok

# ---------------------------------------------------------------- 4. audio (Edge TTS, இலவசம்)
async def _tts(text, out):
    import edge_tts
    await edge_tts.Communicate(text, TTS_VOICE, rate="-8%", pitch="+0Hz", volume="+8%").save(str(out))

TTS_STATE = {"edge_failed": 0}
# ஆடியோ உச்சரிப்பு அகராதி — எழுத்தில் மாறாது; ஒலிக்கும்போது மட்டும்
SAY = {
    "துலாமுள்": "துலா முள்",
    "AI": "ஏ ஐ", "PIB": "பி ஐ பி", "RBI": "ஆர் பி ஐ", "GST": "ஜி எஸ் டி",
    "RTI": "ஆர் டி ஐ", "TNPSC": "டி என் பி எஸ் சி", "UPSC": "யு பி எஸ் சி",
    "SSC": "எஸ் எஸ் சி", "IBPS": "ஐ பி பி எஸ்", "CBI": "சி பி ஐ", "ED": "இ டி",
    "IT": "ஐ டி", "SIR": "எஸ் ஐ ஆர்", "GO": "அரசாணை", "FIR": "எஃப் ஐ ஆர்",
    "CM": "முதல்வர்", "PM": "பிரதமர்", "MLA": "எம் எல் ஏ", "MP": "எம் பி",
    "ISRO": "இஸ்ரோ", "NASA": "நாசா", "WHO": "டபிள்யூ எச் ஓ", "ICMR": "ஐ சி எம் ஆர்",
    "TVK": "டி வி கே", "DMK": "டி எம் கே", "AIADMK": "அ இ அ தி மு க",
    "BJP": "பி ஜே பி", "TASMAC": "டாஸ்மாக்", "CMRL": "சி எம் ஆர் எல்",
    "%": " சதவீதம் ", "₹": " ரூபாய் ", "&": " மற்றும் ", "+": " பிளஸ் ",
}


def speakable(text):
    """ஆடியோவுக்கு உரையைச் சீரமை — உச்சரிப்பு, நிறுத்தற்குறி, இடைவெளி."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    for k, v in SAY.items():                                   # உச்சரிப்பு
        t = t.replace(k, v)
    t = t.replace("—", ", ").replace("–", ", ").replace("·", ", ").replace("|", ", ")
    t = re.sub(r"\(([^)]{1,40})\)", r", \1,", t)                 # அடைப்புக்குறி → இடைநிறுத்தம்
    t = re.sub(r"([\u0B80-\u0BFF])/([\u0B80-\u0BFF])", r"\1 அல்லது \2", t)
    t = re.sub(r"(\d),(\d)", r"\1\2", t)                        # 1,240 → 1240 (எண் உடையாமல்)
    t = re.sub(r"(?<!\d)([.!?])(?=\S)", r"\1 ", t)              # புள்ளிக்குப் பின் இடைவெளி (தசமம் தவிர)
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"(?<!\d)\s*\.\s*(?!\d)", ". ", t)               # தசம எண்ணை உடைக்காது
    t = re.sub(r";\s*", ". ", t)                                # அரைப்புள்ளி → முழு நிறுத்தம்
    t = re.sub(r"\s{2,}", " ", t).strip()
    if t and t[-1] not in ".!?":
        t += "."
    return t

def make_audio(story_id, script):
    out = AUDIO_DIR / f"{story_id}.mp3"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    script = speakable(script)[:2500]
    if TTS_STATE["edge_failed"] < 2:                       # Edge TTS — 2 முறை தோல்வி என்றால் இந்த ஓட்டத்தில் தவிர்
        try:
            asyncio.run(asyncio.wait_for(_tts(script, out), timeout=40))
            if out.exists() and out.stat().st_size > 1000:
                return f"data/audio/{story_id}.mp3"
        except Exception as ex:
            print(f"[tts-edge] {story_id}: {str(ex)[:80]}")
        TTS_STATE["edge_failed"] += 1
    try:                                                   # மாற்று: Google TTS (gTTS), இலவசம்
        from gtts import gTTS
        gTTS(script, lang="ta", slow=False).save(str(out))
        return f"data/audio/{story_id}.mp3"
    except Exception as ex:
        print(f"[tts-gtts] {story_id}: {str(ex)[:80]}")
        return None

# ---------------------------------------------------------------- 5. image (மூலப் படம் மட்டும்; இல்லையெனில் null → ஆப் துறை-அட்டை காட்டும்)
SAFE_HOSTS = ("openverse", "flickr", "staticflickr", "metmuseum", "images.metmuseum",
              "nasa.gov", "si.edu", "artic.edu", "rijksmuseum.nl", "loc.gov", "tile.loc.gov", "unsplash", "pexels", "pixabay", "cdn.pixabay", "pib.gov.in", "isro.gov.in", "rbi.org.in", "mygov.in", "tn.gov.in",
              "india.gov.in", "nic.in", "gov.in", "prsindia.org",
              "wikimedia.org", "wikipedia.org", "unsplash.com", "pexels.com", "pixabay.com")

def _safe_host(u):
    try:
        h = u.split("/")[2].lower()
    except Exception:
        return False
    return any(d in h for d in SAFE_HOSTS)

def wiki_image(term, lang="ta"):
    """விக்கிப்பீடியாவில் ஒரு நபர்/இடம்/நிறுவனத்தின் இலவசப் படம்."""
    try:
        r = requests.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + requests.utils.quote(term.replace(" ", "_")),
                         headers={"User-Agent": "Thulamul/1.0 (news app; info@thulamul.com)"}, timeout=12)
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("type") == "disambiguation":
            return None
        src = ((d.get("originalimage") or {}).get("source") or (d.get("thumbnail") or {}).get("source"))
        if src and _safe_host(src):
            return {"url": src.replace("/thumb/", "/thumb/") if "/thumb/" in src else src,
                    "credit": f"விக்கிமீடியா · {d.get('title', term)}", "license": "CC / பொதுச் சொத்து",
                    "page": (d.get("content_urls", {}).get("desktop", {}) or {}).get("page", "")}
    except Exception:
        pass
    return None

def commons_image(query):
    """Wikimedia Commons தேடல் — பொதுக் காட்சிகள்."""
    try:
        r = requests.get("https://commons.wikimedia.org/w/api.php",
                         params={"action": "query", "generator": "search", "gsrsearch": query + " filetype:bitmap",
                                 "gsrlimit": 3, "gsrnamespace": 6, "prop": "imageinfo",
                                 "iiprop": "url|extmetadata", "iiurlwidth": 1000, "format": "json"},
                         headers={"User-Agent": "Thulamul/1.0 (news app; info@thulamul.com)"}, timeout=15)
        pages = (r.json().get("query") or {}).get("pages") or {}
        for pg in pages.values():
            ii = (pg.get("imageinfo") or [{}])[0]
            url = ii.get("thumburl") or ii.get("url")
            meta = ii.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value", "CC")
            if "Fair" in lic or "Non-free" in lic:
                continue
            author = re.sub("<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:40]
            if url and _safe_host(url):
                return {"url": url, "credit": f"விக்கிமீடியா Commons{' · ' + author if author else ''}", "license": lic}
    except Exception:
        pass
    return None

def openverse_image(query):
    """Openverse — 8 கோடி CC படங்கள்."""
    try:
        r = requests.get("https://api.openverse.org/v1/images/",
                         params={"q": query, "license_type": "commercial,modification", "page_size": 3, "mature": "false"},
                         headers={"User-Agent": "Thulamul/1.0 (info@thulamul.com)"}, timeout=15)
        for it in (r.json().get("results") or []):
            u = it.get("url") or it.get("thumbnail")
            if u:
                return {"url": u, "credit": f"{it.get('creator') or 'Openverse'} · {it.get('source', '')}",
                        "license": (it.get("license") or "cc").upper()}
    except Exception:
        pass
    return None

# துறை வாரியான குறியீட்டுப் படத் தேடல் (stock)
STOCK_Q = {
    "agri":    ["paddy field india", "farmer tamil nadu", "indian agriculture harvest", "coconut farm india"],
    "economy": ["indian rupee currency", "stock market chart", "bank india", "market vendor india"],
    "tech":    ["technology circuit", "smartphone coding", "data server", "artificial intelligence"],
    "health":  ["hospital india", "doctor stethoscope", "medicine pills", "health checkup"],
    "jobs":    ["office workers india", "job interview", "students exam hall", "resume writing"],
    "court":   ["court building india", "law books gavel", "justice scales", "legal documents"],
    "world":   ["world map globe", "united nations flags", "international city skyline"],
    "india":   ["india gate delhi", "indian parliament", "indian flag"],
    "tn":      ["chennai city", "tamil nadu temple", "marina beach chennai"],
    "assembly":["tamil nadu assembly", "government building india", "parliament session india", "legislative assembly"],
    "spirit":  ["hindu temple tamil nadu", "temple gopuram south india", "oil lamp diya", "temple sculpture chola", "meenakshi temple"],
    "cinema":  ["cinema theatre seats", "film camera", "movie projector", "stage lights concert", "indian cinema"],
    "sports":  ["cricket stadium india", "kabaddi", "athletics track", "hockey india", "sports trophy"],
}

# watermark வரக்கூடிய stock முகவரிகள் — தவிர்
WM_BLOCK = ("shutterstock", "gettyimages", "alamy", "dreamstime", "123rf", "istockphoto",
            "depositphotos", "adobestock", "stock.adobe", "watermark", "preview")

def _no_wm(u):
    lu = (u or "").lower()
    return u and lu.startswith("http") and not any(b in lu for b in WM_BLOCK)

def unsplash_image(q):
    k = os.environ.get("UNSPLASH_KEY")
    if not k:
        return None
    try:
        r = requests.get("https://api.unsplash.com/search/photos",
                         params={"query": q, "per_page": 5, "orientation": "landscape", "content_filter": "high"},
                         headers={"Authorization": "Client-ID " + k}, timeout=15).json()
        for it in (r.get("results") or []):
            u = (it.get("urls") or {}).get("regular")
            if _no_wm(u):
                return {"url": u, "credit": f"{(it.get('user') or {}).get('name','Unsplash')} · Unsplash",
                        "license": "Unsplash — இலவசம்", "symbolic": True}
    except Exception:
        pass
    return None

def pexels_image(q):
    k = os.environ.get("PEXELS_KEY")
    if not k:
        return None
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         params={"query": q, "per_page": 5, "orientation": "landscape"},
                         headers={"Authorization": k}, timeout=15).json()
        for it in (r.get("photos") or []):
            u = (it.get("src") or {}).get("large")
            if _no_wm(u):
                return {"url": u, "credit": f"{it.get('photographer','Pexels')} · Pexels",
                        "license": "Pexels — இலவசம்", "symbolic": True}
    except Exception:
        pass
    return None

def pixabay_image(q):
    k = os.environ.get("PIXABAY_KEY")
    if not k:
        return None
    try:
        r = requests.get("https://pixabay.com/api/",
                         params={"key": k, "q": q, "image_type": "photo", "orientation": "horizontal",
                                 "safesearch": "true", "per_page": 5}, timeout=15).json()
        for it in (r.get("hits") or []):
            u = it.get("largeImageURL") or it.get("webformatURL")
            if _no_wm(u):
                return {"url": u, "credit": f"{it.get('user','Pixabay')} · Pixabay",
                        "license": "Pixabay — இலவசம்", "symbolic": True}
    except Exception:
        pass
    return None


def flickr_cc_image(q):
    """Flickr — CC உரிமப் படங்கள் (key இருந்தால்)."""
    k = os.environ.get("FLICKR_KEY")
    if not k:
        return None
    try:
        r = requests.get("https://www.flickr.com/services/rest/",
                         params={"method": "flickr.photos.search", "api_key": k, "text": q,
                                 "license": "1,2,3,4,5,6,9,10", "sort": "relevance", "safe_search": 1,
                                 "content_type": 1, "per_page": 5, "format": "json", "nojsoncallback": 1,
                                 "extras": "url_l,owner_name,license"}, timeout=15).json()
        for it in ((r.get("photos") or {}).get("photo") or []):
            u = it.get("url_l")
            if _no_wm(u):
                return {"url": u, "credit": f"{it.get('ownername','Flickr')} · Flickr", "license": "CC", "symbolic": True}
    except Exception:
        pass
    return None

def met_image(q):
    """The Met Museum — பொதுச் சொத்து கலைப் படைப்புகள் (key தேவையில்லை)."""
    try:
        s1 = requests.get("https://collectionapi.metmuseum.org/public/collection/v1/search",
                          params={"q": q, "hasImages": "true", "isPublicDomain": "true"}, timeout=15).json()
        for oid in (s1.get("objectIDs") or [])[:3]:
            o = requests.get(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}", timeout=15).json()
            u = o.get("primaryImage") or o.get("primaryImageSmall")
            if _no_wm(u):
                return {"url": u, "credit": f"{o.get('artistDisplayName') or 'The Met'} · The Met", "license": "பொதுச் சொத்து", "symbolic": True}
    except Exception:
        pass
    return None

_STOCK_CACHE = {}

def nasa_image(q):
    """NASA — விண்வெளி, பூமி, காலநிலை (பொதுச் சொத்து; key இல்லை)."""
    try:
        r = requests.get("https://images-api.nasa.gov/search",
                         params={"q": q, "media_type": "image"}, timeout=15).json()
        for it in ((r.get("collection") or {}).get("items") or [])[:3]:
            links = it.get("links") or []
            if links and links[0].get("href"):
                d = (it.get("data") or [{}])[0]
                return {"url": links[0]["href"], "credit": f"NASA · {d.get('center','')}",
                        "license": "பொதுச் சொத்து", "symbolic": True}
    except Exception:
        pass
    return None


def smithsonian_image(q):
    """Smithsonian Open Access — வரலாறு, இயற்கை (CC0; key இல்லை)."""
    try:
        r = requests.get("https://api.si.edu/openaccess/api/v1.0/search",
                         params={"q": f"{q} AND online_media_type:Images", "rows": 3,
                                 "api_key": os.environ.get("SI_KEY", "")}, timeout=15).json()
        for row in ((r.get("response") or {}).get("rows") or []):
            media = (((row.get("content") or {}).get("descriptiveNonRepeating") or {})
                     .get("online_media") or {}).get("media") or []
            for md in media:
                u = md.get("content") or md.get("thumbnail")
                if u and str(u).startswith("http"):
                    return {"url": u, "credit": "Smithsonian Open Access", "license": "CC0", "symbolic": True}
    except Exception:
        pass
    return None


def rijks_image(q):
    """Rijksmuseum — பொதுச் சொத்துக் கலை (key விருப்பம்)."""
    k = os.environ.get("RIJKS_KEY")
    if not k:
        return None
    try:
        r = requests.get("https://www.rijksmuseum.nl/api/en/collection",
                         params={"key": k, "q": q, "ps": 3, "imgonly": "true"}, timeout=15).json()
        for a in (r.get("artObjects") or []):
            u = (a.get("webImage") or {}).get("url")
            if u:
                return {"url": u, "credit": f"Rijksmuseum · {a.get('principalOrFirstMaker','')}",
                        "license": "பொதுச் சொத்து", "symbolic": True}
    except Exception:
        pass
    return None


def artic_image(q):
    """Art Institute of Chicago — பொதுச் சொத்துக் கலை (key இல்லை)."""
    try:
        r = requests.get("https://api.artic.edu/api/v1/artworks/search",
                         params={"q": q, "limit": 3, "fields": "id,title,image_id,artist_title,is_public_domain"},
                         timeout=15).json()
        for a in (r.get("data") or []):
            if a.get("image_id") and a.get("is_public_domain"):
                return {"url": f"https://www.artic.edu/iiif/2/{a['image_id']}/full/1200,/0/default.jpg",
                        "credit": f"Art Institute of Chicago · {a.get('artist_title','')}",
                        "license": "பொதுச் சொத்து", "symbolic": True}
    except Exception:
        pass
    return None


def loc_image(q):
    """Library of Congress — வரலாற்றுப் புகைப்படங்கள் (key இல்லை)."""
    try:
        r = requests.get("https://www.loc.gov/photos/", params={"q": q, "fo": "json", "c": 3}, timeout=20).json()
        for it in (r.get("results") or [])[:3]:
            img = it.get("image_url") or []
            if img:
                u = img[-1]
                if u.startswith("//"):
                    u = "https:" + u
                if u.startswith("http"):
                    return {"url": u, "credit": "Library of Congress", "license": "பொதுச் சொத்து", "symbolic": True}
    except Exception:
        pass
    return None


def stock_image(topic, query=""):
    """குறியீட்டுப் படம் — Unsplash → Pexels → Pixabay → Openverse. Watermark உள்ளவை தவிர்க்கப்படும்."""
    tries = [q for q in ([query] if query else []) if q]
    for q in tries[:2]:
        for fn in (unsplash_image, pexels_image, pixabay_image, openverse_image, flickr_cc_image, nasa_image):
            try:
                im = fn(q)
            except Exception:
                im = None
            if im and _no_wm(im.get("url")):
                im["symbolic"] = True
                return im
    return None


# அறியப்பட்ட இடங்கள் — விக்கிமீடியாவில் உறுதியான படம்
PLACE_WIKI = {
    "சென்னை உயர்நீதிமன்ற": "Madras High Court", "மதராஸ் உயர்நீதிமன்ற": "Madras High Court",
    "மதுரை உயர்நீதிமன்ற": "Madras High Court Madurai Bench", "உச்ச நீதிமன்ற": "Supreme Court of India",
    "டெல்லி உயர்நீதிமன்ற": "Delhi High Court", "கேரள உயர்நீதிமன்ற": "Kerala High Court",
    "கர்நாடக உயர்நீதிமன்ற": "Karnataka High Court", "தலைமைச் செயலக": "Fort St. George Chennai",
    "சட்டமன்ற": "Tamil Nadu Legislative Assembly", "ரிசர்வ் வங்கி": "Reserve Bank of India",
    "பாராளுமன்ற": "Parliament House New Delhi", "ராஜ்பவன்": "Raj Bhavan Chennai",
    "சென்ட்ரல் ரயில்": "Chennai Central railway station", "எழும்பூர்": "Chennai Egmore railway station",
    "மெட்ரோ ரயில்": "Chennai Metro", "விமான நிலைய": "Chennai International Airport",
    "மெரினா": "Marina Beach", "ஐஐடி": "IIT Madras", "அண்ணா பல்கலை": "Anna University",
    "இஸ்ரோ": "ISRO", "ஸ்ரீஹரிகோட்டா": "Satish Dhawan Space Centre",
    "மீனாட்சி": "Meenakshi Temple", "மதுரை மீனாட்சி": "Meenakshi Temple",
    "பிரகதீஸ்வரர்": "Brihadeeswarar Temple", "தஞ்சை பெரிய கோயில்": "Brihadeeswarar Temple",
    "ரங்கநாதர்": "Ranganathaswamy Temple, Srirangam", "ஸ்ரீரங்கம்": "Ranganathaswamy Temple, Srirangam",
    "பழனி": "Palani Murugan Temple", "திருச்செந்தூர்": "Thiruchendur Murugan Temple",
    "சிதம்பரம்": "Thillai Nataraja Temple", "காஞ்சி காமாட்சி": "Kamakshi Amman Temple",
    "ராமேஸ்வரம்": "Ramanathaswamy Temple", "திருப்பதி": "Tirumala Venkateswara Temple",
    "வேளாங்கண்ணி": "Basilica of Our Lady of Good Health", "நாகூர்": "Nagore Dargah",
    "கபாலீஸ்வரர்": "Kapaleeshwarar Temple", "மாமல்லபுரம்": "Mahabalipuram",
    "தஞ்சாவூர் கோயில்": "Brihadeeswarar Temple", "வள்ளுவர் சிலை": "Thiruvalluvar Statue",
}


def place_image(headline):
    """செய்தியில் அறியப்பட்ட இடம் இருந்தால் அதன் விக்கிப் படம்."""
    h = str(headline or "")
    for key, en in PLACE_WIKI.items():
        if key in h:
            im = wiki_image(en, "en")
            if im:
                im["symbolic"] = False
                return im
    return None


def image_matches(im, query):
    """படத்தின் விவரத்தில் தேடல் சொல்லின் முக்கியச் சொல் இருக்கிறதா — பொருந்தாத படத்தைத் தவிர்."""
    if not im or not query:
        return False
    hay = (str(im.get("credit", "")) + " " + str(im.get("url", "")) + " " + str(im.get("title", ""))).lower()
    words = [w for w in re.split(r"[^a-z0-9]+", str(query).lower()) if len(w) > 3]
    if not words:
        return True
    return any(w in hay for w in words[:4])


# துறை ↔ ஆங்கிலச் சொல் பொருத்தம் — image_query வேறு துறையைச் சேர்ந்ததா எனச் சோதிக்க
TOPIC_WORDS = {
    "health": {"health", "medical", "medicine", "hospital", "doctor", "patient", "drug", "disease",
               "vaccine", "clinic", "nurse", "pharmacy", "heart", "cancer", "diabetes"},
    "economy": {"economy", "market", "stock", "trading", "bank", "rupee", "finance", "investment",
                "gdp", "inflation", "budget", "tax", "export", "import", "gold", "price"},
    "court": {"court", "justice", "judge", "legal", "law", "verdict", "petition", "tribunal", "gavel"},
    "crime": {"police", "crime", "arrest", "justice", "investigation", "theft", "case", "gavel"},
    "sports": {"sport", "cricket", "hockey", "football", "athlete", "stadium", "medal", "games",
               "kabaddi", "olympic", "player", "match", "tournament"},
    "cinema": {"film", "cinema", "movie", "actor", "actress", "director", "shooting", "poster", "music"},
    "jobs": {"job", "employment", "exam", "recruitment", "students", "office", "interview", "career"},
    "tech": {"technology", "digital", "internet", "mobile", "smartphone", "computer", "software", "app"},
    "govt": {"government", "official", "scheme", "ministry", "parliament", "secretariat", "document"},
}



_BANK = None
_BANK_FLAT = None
_BANK_DF = None
_TA_WORD = re.compile(r"[\u0B80-\u0BFF]+")


def _stems(tag):
    """தமிழ் வேற்றுமை உருபு சேரும்போது சொல்லின் முடிவு மாறும் —
    'விபத்து' → 'விபத்தில்', 'திட்டம்' → 'திட்டத்தில்'.
    அதனால் அடிச்சொல்லையும் சேர்த்துத் தேடு."""
    out = [tag]
    if len(tag) >= 5 and tag[-1] in "\u0bc1\u0bc2":        # ு ூ
        out.append(tag[:-1])
    elif len(tag) >= 6 and tag.endswith("\u0bae\u0bcd"):    # ம்
        out.append(tag[:-2])
    return out


def _bank_load():
    """bank_index.json-ஐ ஒரு முறை ஏற்று, குறிச்சொற்களைத் தயார் செய்."""
    global _BANK, _BANK_FLAT, _BANK_DF
    if _BANK is not None:
        return
    try:
        _BANK = json.loads((DATA / "bank_index.json").read_text(encoding="utf-8"))
    except Exception:
        _BANK = {}
    _BANK_FLAT, _BANK_DF = [], {}
    for t, items in _BANK.items():
        for it in items:
            tags = [w for w in str(it.get("tags") or "").split() if len(w) >= 3]
            for w in set(tags):
                _BANK_DF[w] = _BANK_DF.get(w, 0) + 1
            _BANK_FLAT.append((t, it, tags))


def _bank_rec(it):
    return {"url": it["file"], "credit": "துலாமுள் AI ஓவியம்",
            "license": "சொந்தப் படைப்பு", "symbolic": True, "bank": True}


def story_text(story):
    """தலைப்பு + வரிகள் + முடிவு — படம் தேட."""
    parts = [str(story.get("headline") or "")]
    parts += [str(x) for x in (story.get("lines") or [])]
    parts.append(str(story.get("closing") or ""))
    return " ".join(parts)


def bank_best(topic, text=""):
    """குறிச்சொல் பொருத்தம் → (படம், மதிப்பெண்).

    விதி 1 — குறிச்சொல் செய்திச் சொல்லின் *தொடக்கமாக* இருக்க வேண்டும்
      ('கொலை' → 'கொலையில்' ஆம்; 'உதவி' → 'கழிவுநீரை' இல்லை).
      சொல்லின் நடுவில் தேடினால் பொதுச் சொற்கள் தற்செயலாகப் பொருந்தும்.
    விதி 2 — அதே துறையில் 2 சொல் பொருந்தினால் போதும்.
    விதி 3 — வேறு துறையின் படம் எடுக்க, பொருந்திய சொற்களில்
      குறைந்தது ஒன்று *அரியதாக* (களஞ்சியத்தில் 3 படத்திற்கு மேல்
      வராத சொல்) இருக்க வேண்டும். 'அரசு', 'திட்டம்', 'பாதுகாப்பு'
      போன்ற பொதுச் சொற்கள் மட்டும் பொருந்தினால் ஏற்காதே."""
    _bank_load()
    words = _TA_WORD.findall(str(text or "")[:800])
    if not words or not _BANK_FLAT:
        return None, 0

    def score(tags):
        n = rare = 0
        for tg in tags:
            if any(w.startswith(st) or (len(w) >= 5 and st.startswith(w))
                   for st in _stems(tg) for w in words):
                n += 1
                if _BANK_DF.get(tg, 99) <= 3:
                    rare += 1
        return n, rare

    best, bs = None, 0
    for t, it, tags in _BANK_FLAT:
        if t != topic:
            continue
        n, _r = score(tags)
        if n > bs:
            best, bs = it, n
    if bs >= 2:                        # அதே துறையில் வலுவான பொருத்தம்
        return _bank_rec(best), bs

    b2, s2 = None, 1                   # வேறு துறை — 2 சொல் + ஒரு அரிய சொல்
    for t, it, tags in _BANK_FLAT:
        n, rare = score(tags)
        if n > s2 and rare >= 1:
            b2, s2 = it, n
    if b2 is not None:
        return _bank_rec(b2), s2
    if bs >= 1:                        # பலவீனம் — கடைசி வழியாக மட்டும்
        return _bank_rec(best), bs
    return None, 0


def bank_image(topic, headline="", text=""):
    """களஞ்சியப் படம் — முதலில் குறிச்சொல், இல்லையேல் நிலையான சுழற்சி."""
    rec, _ = bank_best(topic, text or headline)
    if rec:
        return rec
    _bank_load()
    items = _BANK.get(topic) or []
    if not items:
        return None
    k = sum(ord(ch) for ch in str(headline)[:40]) % len(items)
    return _bank_rec(items[k])


def query_fits(story):
    """image_query / wiki_subject செய்தியின் துறையுடன் பொருந்துகிறதா?
    வேறு துறையின் சொல் இருந்தால் — படம் வேண்டாம் (தவறான படத்தைவிட மேல்)."""
    topic = story.get("topic") or ""
    blob = ((story.get("image_query") or "") + " " + (story.get("wiki_subject") or "")).lower()
    if not blob.strip():
        return True
    words = set(re.findall(r"[a-z]+", blob))
    mine = TOPIC_WORDS.get(topic, set())
    for t, ws in TOPIC_WORDS.items():
        if t == topic:
            continue
        if words & ws and not (words & mine):
            return False                      # வேறு துறையின் சொல் மட்டும் — பொருந்தாது
    return True


def pick_image(c, story=None):
    """படம் — தவறான படத்தைவிட படமே இல்லாதது மேல்."""
    for i in c["items"]:
        u = i.get("image") or ""
        if u and _safe_host(u):
            return {"url": u, "credit": i["source"], "license": "அரசு / திறந்த உரிமம்"}
    if not story:
        return None

    topic = story.get("topic") or c.get("topic_hint") or ""
    txt = story_text(story)
    bk, bs = bank_best(topic, txt)

    if not query_fits(story):
        print("[image] தேடல் பொருந்தவில்லை → களஞ்சியம்:", str(story.get("headline"))[:34])
        return bk or bank_image(topic, story.get("headline"), txt)

    # 1) AI தந்த விக்கிப்பீடியாத் தலைப்பு — மிகத் துல்லியம்
    ws = (story.get("wiki_subject") or "").strip()
    if ws and len(ws) > 3 and ws.lower() not in ("temple", "court", "minister", "government"):
        im = wiki_image(ws, "en")
        if im:
            im["symbolic"] = False
            return im
    pl = place_image(story.get("headline"))
    if pl:
        return pl

    person = (story.get("person_en") or "").strip()
    if person:
        im = wiki_image(person, "en") or wiki_image(person, "ta")
        if im:
            im["symbolic"] = False
            return im
        return None

    # 2) களஞ்சியத்தில் வலுவான பொருத்தம் (2+ குறிச்சொல்) →
    #    பொது stock படத்தைவிட இதுவே துல்லியம்
    if bs >= 2:
        print(f"[image] களஞ்சியம் ({bs} சொல்):", str(story.get("headline"))[:34])
        return bk

    if topic == "crime":
        return bk or bank_image("crime", story.get("headline"), txt)

    q = (story.get("image_query") or "").strip()
    if q:
        im = commons_image(q)
        if im and image_matches(im, q):
            im["symbolic"] = True
            return im
        im = stock_image("", q)
        if im and image_matches(im, q):
            im["symbolic"] = True
            return im
    return bk or bank_image(topic, story.get("headline"), txt)

def telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=15)
    except Exception as ex:
        print("[telegram]", ex)

def telegram_poll_approvals(state):
    """Telegram-ல் '✔ id' அல்லது '✘ id' என்று அனுப்பியதைப் படித்து pending → published/rejected."""
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        return {}
    try:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates",
                         params={"offset": state.get("tg_offset", 0) + 1, "timeout": 0}, timeout=15).json()
    except Exception as ex:
        print("[telegram poll]", ex); return {}
    decisions = {}
    for u in r.get("result", []):
        state["tg_offset"] = max(state.get("tg_offset", 0), u["update_id"])
        t = (u.get("message") or {}).get("text", "").strip()
        m = re.match(r"^(✔|✓|ok|சரி|✘|✗|no|வேண்டாம்)\s*([a-f0-9]{12})", t, re.I)
        if m:
            decisions[m.group(2)] = m.group(1) in ("✔", "✓", "ok", "சரி")
        if re.match(r"^(✘|✗|no|வேண்டாம்)\s*comic", t, re.I):
            try:
                import importlib, sys
                sys.path.insert(0, str(ROOT / "pipeline"))
                importlib.import_module("comic").hide_today(now.strftime("%Y-%m-%d"))
                telegram("இன்றைய காமிக்ஸ் மறைக்கப்பட்டது.")
            except Exception as ex:
                telegram("காமிக்ஸ் மறைக்க முடியவில்லை: " + str(ex)[:80])
        elif re.match(r"^(✘|✗|no|வேண்டாம்)\s*editorial", t, re.I):
            ed = load_json(DATA / "ai_editorial.json", {}); ed["hidden"] = True; save_json(DATA / "ai_editorial.json", ed); telegram("இன்றைய AI தலையங்கம் மறைக்கப்பட்டது.")
        # தலையங்கம்: "தலையங்கம்: தலைப்பு\nஉரை..."
        if t.startswith("தலையங்கம்:"):
            body = t[len("தலையங்கம்:"):].strip()
            title, _, rest = body.partition("\n")
            eds = load_json(DATA / "editorials.json", [])
            eds.insert(0, {"id": item_id(title + str(time.time())), "title": title.strip(),
                           "body": rest.strip(), "author": "ஆசிரியர் · ல. ராஜ்குமார்",
                           "date": datetime.now(IST).strftime("%Y-%m-%d")})
            save_json(DATA / "editorials.json", eds[:100])
            telegram(f"தலையங்கம் வெளியானது: {title.strip()}")
    return decisions

# ---------------------------------------------------------------- main
def main():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    sources = yaml.safe_load((ROOT / "pipeline/sources.yaml").read_text(encoding="utf-8"))
    prompt = (ROOT / "pipeline/prompts/news_5line.md").read_text(encoding="utf-8")
    state = load_json(STATE_FILE, {"seen": [], "tg_offset": 0})
    seen = set(state["seen"])
    feed = load_json(FEED_FILE, [])
    pending = load_json(PENDING_FILE, [])
    client = Anthropic(timeout=180, max_retries=2)   # ANTHROPIC_API_KEY env-லிருந்து

    # 0. முந்தைய ஓட்டத்தின் Telegram முடிவுகள்
    decisions = telegram_poll_approvals(state)
    still = []
    HOLD_FLAGS = {"defamation_risk", "communal", "numbers_conflict"}
    for p in pending:
        d = decisions.get(p["id"])
        # புதிய விதி: மென்மையான flag மட்டும் (single_source போன்றவை) → தானாக வெளியீடு
        if d is None and not (HOLD_FLAGS & set(p.get("flags", []))) and p.get("confidence", 1) >= AUTO_PUBLISH_MIN_CONFIDENCE:
            d = True
        if d is True:
            p["status"] = "published"; feed.insert(0, p); print("[approve]", p["id"])
        elif d is False:
            print("[reject]", p["id"])
        elif time.time() - p["created_ts"] > 6 * 3600:
            print("[expire]", p["id"])          # 6 மணி பதில் இல்லை → கைவிடு
        else:
            still.append(p)
    pending = still

    # 1–2. fetch + cluster
    fresh = fetch_all(sources, seen)
    clusters = cluster(fresh)
    print(f"[run] புதியவை {len(fresh)} → நிகழ்வுகள் {len(clusters)}")

    # 3–5. write / audio / publish
    t_start = time.time()
    written = 0
    # தினசரி குறைந்தபட்சம்: இன்று 0 உள்ள துறைகளின் நிகழ்வுகளை முதலில் எழுது
    today_topics = {x["topic"] for x in feed if x.get("published_at", "").startswith(today)}
    TOPIC_CAP = {"tn": 10, "india": 6, "world": 6, "economy": 6, "crime": 6, "court": 5,
             "govt": 5, "jobs": 5, "sports": 5, "cinema": 4, "health": 4, "assembly": 3, "tech": 2}
    todays_count = {}
    for x in feed:
        if str(x.get("published_at", ""))[:10] == today and x.get("status") == "published":
            todays_count[x.get("topic")] = todays_count.get(x.get("topic"), 0) + 1
    api_dead = False
    # triage — 2 மணிக்கு ஒரு முறை (செலவுக் கட்டுப்பாடு); இடையில் சேமித்ததைப் பயன்படுத்து
    _tri = load_json(DATA / "triage_cache.json", {})
    _fresh = (time.time() - float(_tri.get("at", 0))) < 7200
    if clusters and not _fresh:
        scores = triage(client, clusters)
        _keys = {c["items"][0]["title"][:60]: sc for sc, c in zip(
            [scores.get(n, 5) for n in range(len(clusters))], clusters)}
        save_json(DATA / "triage_cache.json", {"at": time.time(), "k": _keys})
    else:
        _k = _tri.get("k", {})
        scores = {n: _k.get(c["items"][0]["title"][:60], 6) for n, c in enumerate(clusters)}
        if clusters:
            print(f"[triage] சேமித்த மதிப்பெண் ({len(_k)}) — புதிய அழைப்பு இல்லை")
    if scores:
        scored = [(scores.get(n, 5), n, c) for n, c in enumerate(clusters)]
        keep = [x for x in scored if x[0] >= MIN_SCORE]
        # ஒவ்வொரு பக்கத்திற்கும் குறைந்தபட்ச இடம் — பக்கம் காலியாகக் கூடாது
        PAGE_MIN = {"tn": 6, "india": 4, "world": 3, "economy": 3, "court": 3, "govt": 4,
                    "crime": 4, "jobs": 3, "health": 3, "cinema": 3, "sports": 3, "assembly": 2}
        have = {}
        for sc, n, c in keep:
            t = c["topic_hint"]; have[t] = have.get(t, 0) + 1
        todays = {}
        for x in feed:
            if str(x.get("published_at", ""))[:10] == today and x.get("status") == "published":
                todays[x.get("topic")] = todays.get(x.get("topic"), 0) + 1
        kept_ids = {id(c) for _, _, c in keep}
        for t, need in PAGE_MIN.items():
            short = need - have.get(t, 0) - todays.get(t, 0)
            if short <= 0:
                continue
            extra = [x for x in scored if x[2]["topic_hint"] == t and id(x[2]) not in kept_ids]
            if not extra and t == "govt":      # அரசு feed காலி — பொது feed-லிருந்து எடு
                extra = [x for x in scored if x[2]["topic_hint"] in ("tn", "india") and id(x[2]) not in kept_ids]
            extra.sort(key=lambda x: -x[0])
            for x in extra[:short]:
                keep.append(x); kept_ids.add(id(x[2]))
        # காலியான பக்கங்களுக்கு முன்னுரிமை — சுழற்சி முறை
        need = {t: max(0, n - todays.get(t, 0)) for t, n in PAGE_MIN.items()}
        keep.sort(key=lambda x: (-need.get(x[2]["topic_hint"], 0), -x[0]))
        by_topic = {}
        for item in keep:
            by_topic.setdefault(item[2]["topic_hint"], []).append(item)
        rr, idx = [], 0
        while any(by_topic.values()):
            for t in sorted(by_topic, key=lambda t: -need.get(t, 0)):
                if by_topic[t]:
                    rr.append(by_topic[t].pop(0))
            idx += 1
            if idx > 60:
                break
        keep = rr
        print(f"[triage] {len(clusters)} → {len(keep)} | காலி: " +
              ", ".join(f"{t}:{n}" for t, n in sorted(need.items(), key=lambda x: -x[1])[:5] if n))
        for sc, _, c in keep:
            c["score"] = sc
        clusters = [c for _, _, c in keep]
    boosted = set()
    def prio(c):
        t = c["topic_hint"]
        if t in THIN and t not in today_topics and t not in boosted:
            boosted.add(t); return (0, 0)
        return (1, -(c.get("score", 5) * 10 + len(c["items"])))   # முக்கியத்துவம் → பல மூலம்
    clusters.sort(key=prio)
    def mark_seen(c):
        for i in c["items"]:
            seen.add(i["id"])
    push_items = []
    day_count = state.get("day_count", {}).get(today, 0)
    for c in clusters:
        if api_dead or written >= MAX_NEW_PER_RUN or day_count + written >= MAX_PER_DAY or time.time() - t_start > 15 * 60:
            continue                      # அடுத்த ஓட்டத்தில் எடுக்கும்; seen-ல் சேர்க்காது
        _t = c["topic_hint"]
        if todays_count.get(_t, 0) >= TOPIC_CAP.get(_t, 8):
            continue                      # இந்தப் பக்கம் இன்று நிரம்பிவிட்டது
        ok, extra_flags = eligible(c)
        if not ok:
            print(f"[மூலம்] ஒரே ஊடகம் ({c['topic_hint']}) — வெளியிடப்படவில்லை: {c['items'][0]['title'][:48]}")
            continue
        try:
            _big = (c["topic_hint"] in BIG_TOPICS) or len(c["items"]) >= 2 \
                   or any(i.get("grade") == "official" for i in c["items"]) or c.get("score", 5) >= 8
            story = write_news(client, prompt, c, today, MODEL if _big else MODEL_FAST)
        except Exception as ex:
            msg = str(ex); print("[claude] பிழை", msg[:200])
            if "credit" in msg or "authentication" in msg or "401" in msg or "402" in msg:
                api_dead = True
                if state.get("alert_day") != today:
                    telegram("⚠️ <b>துலாமுள் நின்றுவிட்டது</b>\nAnthropic credit தீர்ந்தது / key பிழை. console.anthropic.com → Billing → Add credits.")
                    state["alert_day"] = today
            continue   # பிழை → அடுத்த ஓட்டத்தில் மீண்டும் முயற்சி
        if story.get("skip"):
            print("[skip]", (story.get("reason") or "")[:60]); mark_seen(c); continue
        if not validate(story):
            print("[validate] தவறான வடிவம், தவிர்க்கப்பட்டது"); mark_seen(c); continue
        # உரைத் தரக் காவல் — 2 திருத்த முயற்சி; பிறகும் பிழை என்றால் வெளியிடாது
        # உரை + உண்மை — ஒரே சோதனை, ஒரே திருத்த முயற்சி (செலவுக் கட்டுப்பாடு)
        _src = " ".join((i.get("title", "") + " " + i.get("text", "")) for i in c["items"])
        try:                                   # கட்டாயப் பிழைதிருத்தம் (Haiku)
            _before = story.get("headline", "")
            story = proofread(client, story, _src)
            if story.get("headline", "") != _before:
                print("[திருத்தம்]", _before[:40], "→", story.get("headline", "")[:40])
        except Exception as ex:
            print("[திருத்தம்] பிழை", str(ex)[:80])
        _errs = text_problems(story) + fact_problems(story, _src)
        if _errs:
            print(f"[தரம்] {'; '.join(_errs[:2])} → ஒரு திருத்தம்")
            try:
                story = fix_text(client, story, _errs + ["மூல உரையில் உள்ள எண்களை மட்டும் பயன்படுத்து"])
                _errs = text_problems(story) + fact_problems(story, _src)
            except Exception as ex:
                print("[தரம்] திருத்தப் பிழை", str(ex)[:80])
        if _errs:
            print("[தரம்] தோல்வி — வெளியிடப்படவில்லை:", "; ".join(_errs[:2]))
            mark_seen(c); continue
        _dup = is_duplicate(story, feed, today)
        if _dup:
            print("[நகல்] ஏற்கனவே வெளியானது:", _dup)
            mark_seen(c); continue
        mark_seen(c)
        written += 1
        state.setdefault("day_count", {})[today] = day_count + written
        sid = c["items"][0]["id"]
        story["id"] = sid
        story["flags"] = sorted(set(story.get("flags", []) + extra_flags))
        story["topic_ta"] = TOPIC_TA[story["topic"]]
        story["published_at"] = datetime.now(IST).isoformat(timespec="minutes")
        story["links"] = [i["link"] for i in c["items"]]
        story["image"] = pick_image(c, story)
        story["audio"] = make_audio(sid, ". ".join([story["headline"].rstrip(".")] + [l.rstrip(".") for l in story["lines"]] + [story["closing"].rstrip(".")]) + ".")
        story["created_ts"] = time.time()
        story["front_cat"] = str(story.get("front_cat") or "routine")
        story["image_query"] = str(story.get("image_query") or "")
        story["person_en"] = str(story.get("person_en") or "")
        story["wiki_subject"] = str(story.get("wiki_subject") or "")
        story["urgent"] = bool(story.get("urgent"))
        story["affected"] = str(story.get("affected") or "")

        HOLD_FLAGS = {"defamation_risk", "communal", "numbers_conflict"}
        hold = bool(HOLD_FLAGS & set(story["flags"])) or story.get("confidence", 1) < AUTO_PUBLISH_MIN_CONFIDENCE
        if hold:
            story["status"] = "pending"; pending.append(story)
            telegram(f"⚖️ <b>சரிபார்க்க</b> [{', '.join(story['flags']) or 'குறைந்த நம்பிக்கை'}]\n"
                     f"<b>{story['headline']}</b>\n" + "\n".join(story["lines"]) +
                     f"\n\nமூலம்: {', '.join(s['name'] for s in story['sources'])}\n"
                     f"பதில்: <code>✔ {sid}</code> அல்லது <code>✘ {sid}</code>")
            print("[hold]", story["headline"])
        else:
            if any(x.get("headline") == story["headline"] for x in feed[:200]):
                print("[dup] அதே தலைப்பு உள்ளது; தவிர்"); mark_seen(c); continue
            story["status"] = "published"; feed.insert(0, story)
            todays_count[story["topic"]] = todays_count.get(story["topic"], 0) + 1
            if len(story.get("sources", [])) >= 2 or story.get("confidence", 0) >= 0.8:
                push_items.append({"topic": story["topic"], "title": story["headline"],
                                   "body": story["lines"][0][:140], "url": f"./#story/{story['id']}",
                                   "tag": story["id"], "front": len(story.get("sources", [])) >= 3})
            print("[publish]", story["headline"])
        save_json(FEED_FILE, dedupe_feed(feed, today)[:300]); save_json(PENDING_FILE, pending)
        state["seen"] = list(seen)[-5000:]; save_json(STATE_FILE, state)   # ஒவ்வொன்றுக்கும் உடனே சேமி

    # 5b. காலை brief — 6:00–6:29 IST ஓட்டத்தில் (அல்லது இன்று இன்னும் இல்லையெனில்)
    now = datetime.now(IST)
    brief = load_json(DATA / "brief.json", {})
    if now.hour >= 6 and brief.get("date") != today and feed:
        top = [x for x in feed if x["status"] == "published"][:5]
        script = f"துலாமுள் — {now.strftime('%d')} தேதி காலை செய்திகள். " + " ".join(
            f"{n+1}. {x['headline']}. {x['lines'][0]}" for n, x in enumerate(top)) + " இன்றைய முழுச் செய்திகள் துலாமுள் ஆப்பில்."
        audio = make_audio(f"brief_{today}", script)
        save_json(DATA / "brief.json", {"date": today, "items": [x["id"] for x in top],
                                        "headlines": [x["headline"] for x in top], "audio": audio})
        print("[brief] காலை brief தயார்")

    # 5a2. மெல்லிய பக்கங்களுக்குக் கட்டுரை நிரப்பு
    try:
        if not api_dead:
            _made = 0
            for t in (FILLER_TOPICS if now.hour >= 11 else []):
                if _made >= 1:
                    break
                todays = [x for x in feed if x.get("topic") == t and str(x.get("published_at", ""))[:10] == today and x["status"] == "published"]
                if len(todays) < 1 and not any(x.get("kind") == "article" for x in todays):
                    _made += 1
                    art = write_filler(client, t, today, now)
                    if art:
                        art["image"] = stock_image("", {
                            "health": "healthy food india", "world": "united nations flags",
                            "economy": "indian rupee coins finance", "court": "law books gavel",
                            "govt": "government office india", "tech": "smartphone payment india",
                            "sports": "kabaddi players india", "cinema": "film camera cinema",
                            "india": "indian parliament building", "crime": "scales of justice",
                            "jobs": "students writing exam india"}.get(t, ""))
                        feed.insert(0, art); print(f"[filler] {t} கட்டுரை")
    except Exception as ex:
        print("[filler] பிழை", str(ex)[:120])

    # 5b1. இன்றைய வேலை அறிவிப்புகள் — தினமும் ஒரு தொகுப்பு (8:00-க்குப் பின், ஒரு முறை)
    try:
        jd = load_json(DATA / "jobs_digest.json", {})
        if now.hour >= 7 and jd.get("date") != today and not api_dead:
            raw_items = [i for i in fresh if i["topic_hint"] == "jobs"][:25]
            if raw_items:
                src_text = "\n\n".join(f"[{i['source']}] {i['title']}\n{i['text'][:600]}\n{i['link']}" for i in raw_items)
                jp = ("நீ துலாமுள் நாளிதழின் வேலைவாய்ப்பு பக்க எழுத்தாளர். கீழே உள்ள மூலங்களிலிருந்து இன்றைய வேலை அறிவிப்புகளை JSON-ஆக மட்டும் தொகு: "
                      '{"items":[{"org":"நிறுவனம்/துறை","post":"பதவி","count":"இடங்கள் அல்லது null","last_date":"YYYY-MM-DD அல்லது null","type":"அரசு|தனியார்","link":"url"}]} '
                      "உண்மைகள் மட்டும்; மூலத்தில் இல்லாததைச் சேர்க்காதே; ஒரே அறிவிப்பு இரு முறை வேண்டாம்; அதிகபட்சம் 12. தமிழில் org/post.")
                msg = client.messages.create(model=MODEL, max_tokens=3000, system=cached(jp), messages=[{"role": "user", "content": src_text}])
                rw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
                j = parse_json(client, rw); items = j.get("items", [])
                if items:
                    sid = "jobs_" + today.replace("-", "")
                    story = {"id": sid, "headline": f"இன்றைய வேலை அறிவிப்புகள் — {len(items)} · அரசு & தனியார்",
                             "lines": [f"{x['org']} — {x['post']}" + (f" ({x['count']} இடங்கள்)" if x.get("count") else "") + (f" · கடைசி நாள் {x['last_date']}" if x.get("last_date") else "") for x in items[:5]],
                             "closing": "விண்ணப்பிக்கும் முன் அதிகாரப்பூர்வ அறிவிப்பை சரிபார்க்கவும்; துலாமுள் பணம் கேட்கும் எந்த அறிவிப்பையும் பட்டியலிடாது.",
                             "closing_type": "watch", "sources": [{"name": i["source"], "doc": None, "date": today} for i in raw_items[:4]],
                             "topic": "jobs", "topic_ta": TOPIC_TA["jobs"], "entities": [x["org"] for x in items[:4]], "confidence": 0.8, "flags": [],
                             "jobs": items, "image": None, "status": "published", "published_at": datetime.now(IST).isoformat(timespec="minutes"), "created_ts": time.time()}
                    story["audio"] = make_audio(sid, story["headline"] + ". " + " ".join(story["lines"]))
                    feed.insert(0, story); save_json(DATA / "jobs_digest.json", {"date": today, "count": len(items)})
                    print("[jobs] தொகுப்பு", len(items))
    except Exception as ex:
        print("[jobs] பிழை", ex)

    # 5c. வாரமலர் — ஞாயிறு இணைப்பு (பக்கம் 17)
    try:
        week = now.strftime("%G-W%V")
        malar = load_json(DATA / "malar.json", {})
        if malar.get("v", 0) in (13, 14) and not api_dead:
            # திரை விமர்சனம் + நையாண்டி மட்டும் மீண்டும்; மற்ற பகுதிகள் தொடப்படாது
            import importlib, sys
            sys.path.insert(0, str(ROOT / "pipeline"))
            mal = importlib.import_module("malar")
            _cin = "\n".join(f"- {x.get('headline','')}: {' '.join((x.get('lines') or [])[:2])}"
                             for x in feed if x.get("topic") == "cinema")[:6000]
            got = mal.refresh_parts(client, MODEL, malar, today, ("films", "satire"), _cin, telegram)
            if got:
                save_json(DATA / "malar.json", got); print("[malar] பகுதிகள் புதுப்பிக்கப்பட்டன")
        elif (now.weekday() == 6 and malar.get("films_week") != week and not api_dead):
            # வாரமலர் உறைந்தது — ஞாயிறு திரை விமர்சனம் மட்டும் புதுப்பிப்பு
            import importlib, sys
            sys.path.insert(0, str(ROOT / "pipeline"))
            mal = importlib.import_module("malar")
            _cin = "\n".join(f"- {x.get('headline','')}: {' '.join((x.get('lines') or [])[:2])}"
                             for x in feed if x.get("topic") == "cinema")[:6000]
            got = mal.refresh_parts(client, MODEL, malar, today, ("films",), _cin, telegram)
            if got:
                got["films_week"] = week
                save_json(DATA / "malar.json", got)
                print("[malar] திரை விமர்சனம் மட்டும் (மற்ற பகுதிகள் உறைந்தவை)")
        elif False and malar.get("week") == week and 15 <= malar.get("v", 0) < 16 and not api_dead:
            # இருக்கும் இதழ் — உரையை மாற்றாமல் விடுபட்ட படங்களை மட்டும் சேர்
            import importlib, sys
            sys.path.insert(0, str(ROOT / "pipeline"))
            mal = importlib.import_module("malar")
            heads = "\n".join(x.get("headline", "") for x in feed[:25])
            got = mal.topup(client, MODEL, malar, today, heads, telegram)
            if got:
                save_json(DATA / "malar.json", got); print("[malar] படங்கள் சேர்க்கப்பட்டன")
                try:
                    n = mal.archive(got, DATA / "malar_archive.json"); print(f"[malar] காப்பகம் {n} வாரம்")
                except Exception as ex:
                    print("[malar] காப்பக பிழை", str(ex)[:80])
        elif malar.get("v", 0) < 13 and not api_dead:   # முதல் உருவாக்கம் மட்டும்; பிறகு உறைவு
            import importlib, sys
            sys.path.insert(0, str(ROOT / "pipeline"))
            mal = importlib.import_module("malar")
            wk_start = now - timedelta(days=6)
            dates_ta = f"{wk_start.day} {TA_MONTHS[wk_start.month-1]} – {now.day} {TA_MONTHS[now.month-1]}"
            _ld = state.get("launch_date") or os.environ.get("LAUNCH_DATE") or "2026-09-06"
            _ly, _lm, _ldd = (int(x) for x in _ld.split("-"))
            issue = max(1, (now.date() - date(_ly, _lm, _ldd)).days // 7 + 1)
            done = [b.get("title_en", "") for old in [malar] for b in (old.get("books") or [])]
            done += load_json(DATA / "malar_books.json", [])
            done_heroes = load_json(DATA / "malar_heroes.json", [])
            _cin = "\n".join(f"- {x.get('headline','')}: {' '.join((x.get('lines') or [])[:2])}"
                             for x in feed if x.get("topic") == "cinema")[:6000]
            mm2 = mal.build(client, MODEL, week, today, issue, dates_ta, done, done_heroes, telegram, _cin)
            if mm2:
                save_json(DATA / "malar.json", mm2)
                save_json(DATA / "malar_books.json", (done + [b.get("title_en", "") for b in mm2.get("books", [])])[-60:])
                try:
                    # LAUNCH_REUSE=1 என்றால், காலம் சாராத பகுதிகளைக் காப்பகத்திலிருந்து எடு
                    if os.environ.get("LAUNCH_REUSE") == "1":
                        mm2, src_wk = mal.restore(mm2, DATA / "malar_archive.json",
                                                  load_json(DATA / "malar_reused.json", []))
                        if src_wk:
                            save_json(DATA / "malar_reused.json",
                                      load_json(DATA / "malar_reused.json", []) + [src_wk])
                            print(f"[malar] {src_wk} காப்பகப் பகுதிகள் மீண்டும்")
                    n = mal.archive(mm2, DATA / "malar_archive.json"); print(f"[malar] காப்பகம் {n} வாரம்")
                except Exception as ex:
                    print("[malar] காப்பக பிழை", str(ex)[:80])
                hn = (mm2.get("hero") or {}).get("name", "")
                if hn:
                    save_json(DATA / "malar_heroes.json", (done_heroes + [hn])[-80:])
                print(f"[malar] இதழ் {issue} தயார்")
    except Exception as ex:
        print("[malar] பிழை", str(ex)[:200])

    # 5b4. AI தலையங்கம் "தராசில் இன்று" + கேலிச்சித்திரம் — தினமும் 5:30-க்குப் பின் ஒரு முறை
    try:
        ed = load_json(DATA / "ai_editorial.json", {})
        todays_pub = [x for x in feed if x.get("published_at", "").startswith(today) and x["status"] == "published" and x["topic"] in ("tn", "india", "world", "economy", "court", "health", "agri", "assembly")]
        if now.hour >= 4 and ed.get("date") != today and len(todays_pub) >= 2 and not api_dead:
            src = "\n\n".join(f"[{x['topic_ta']}] {x['headline']}\n" + " ".join(x["lines"]) for x in todays_pub[:10])
            ep = (ROOT / "pipeline/prompts/editorial.md").read_text(encoding="utf-8").replace("{{TODAY}}", today)
            msg = client.messages.create(model=MODEL, max_tokens=3000, system=cached(ep), messages=[{"role": "user", "content": src}])
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            e = parse_json(client, raw); e["date"] = today; e["author"] = "Mr. X"
            e["audio"] = make_audio(f"editorial_{today.replace('-', '')}", f"தராசில் இன்று. {e['title']}. {e['issue']} ஒரு தட்டு: {e['side_a']['label']}. " + " ".join(e["side_a"]["points"]) + f" மறு தட்டு: {e['side_b']['label']}. " + " ".join(e["side_b"]["points"]) + " " + e["question"])
            e["cartoon"]["image"] = make_cartoon(e["cartoon"].get("scene_en", ""), today, e["cartoon"].get("caption_ta", "")); e["cartoon_v"] = 7
            save_json(DATA / "ai_editorial.json", e); print("[editorial] தராசில் இன்று:", e["title"])
            telegram(f"⚖️ <b>தராசில் இன்று</b> — {e['title']}\n{e['question']}\n\n🖼 {e['cartoon'].get('caption_ta','')}\n{'படம் தயார்' if e['cartoon'].get('image') else 'படம் இல்லை'}\n\nதவறு என்றால் <code>✘ editorial</code>")
        elif ed.get("date") == today and (not ed.get("cartoon", {}).get("image") or ed.get("cartoon_v") != 7) and not api_dead:
            img = make_cartoon(ed.get("cartoon", {}).get("scene_en", ""), today, ed.get("cartoon", {}).get("caption_ta", ""))   # படம் மட்டும் மீண்டும்
            if img:
                ed["cartoon"]["image"] = img; ed["cartoon_v"] = 7; save_json(DATA / "ai_editorial.json", ed); print("[cartoon] படம் தயார்")
    except Exception as ex:
        print("[editorial] பிழை", str(ex)[:200])

    # 5b5. பொன்னியின் செல்வன் தினசரிக் காமிக்ஸ் (பக்கம் 18)
    try:
        if not api_dead:
            import importlib, sys
            sys.path.insert(0, str(ROOT / "pipeline"))
            comic_mod = importlib.import_module("comic")
            comic_mod.build(client, MODEL, today, telegram)
    except Exception as ex:
        print("[comic] பிழை", str(ex)[:200])

    # 5b3. ராசிபலன் + பஞ்சாங்கம் — தினமும் ஒரு முறை (Claude தேவையில்லை)
    try:
        rs = load_json(DATA / "rasi.json", {})
        if rs.get("date") != today:
            import importlib, sys
            sys.path.insert(0, str(ROOT / "pipeline")); rasi_mod = importlib.import_module("rasi")
            rs = rasi_mod.build(now.date())
            for r in rs["rasi"]:
                r["audio"] = make_audio(f"rasi_{today.replace('-', '')}_{rs['rasi'].index(r)+1}", f"{r['rasi']} ராசி, இன்று. " + " ".join(r["lines"]))
            save_json(DATA / "rasi.json", rs); print("[rasi] ராசிபலன் தயார்")
    except Exception as ex:
        print("[rasi] பிழை", ex)

    # 5b8. ஏற்கனவே வெளியான செய்திகளில் எழுத்துப் பிழை — திருத்து அல்லது நீக்கு
    try:
        if not api_dead:
            fixed = dropped = 0
            _done = set(load_json(DATA / "repaired.json", []))
            for x in list(feed):
                if str(x.get("published_at", ""))[:10] != today or x.get("status") != "published":
                    continue
                if x.get("id") in _done:
                    continue                      # ஒரு முறை மட்டும் — மீண்டும் செலவு இல்லை
                if fixed + dropped >= 6:
                    break
                _done.add(x.get("id"))
                errs = text_problems(x)
                if not errs:
                    continue
                try:
                    x2 = fix_text(client, dict(x), errs)
                    if not text_problems(x2):
                        x.update({k: x2[k] for k in ("headline", "lines", "closing") if k in x2})
                        x["audio"] = make_audio(x["id"], x["headline"] + ". " + " ".join(x.get("lines", [])))
                        fixed += 1
                        continue
                except Exception:
                    pass
                feed.remove(x); dropped += 1
            save_json(DATA / "repaired.json", list(_done)[-400:])
            if fixed or dropped:
                print(f"[தரம்] பழையவை: {fixed} திருத்தம், {dropped} நீக்கம்")
    except Exception as ex:
        print("[தரம்] சுத்தப்படுத்தல் பிழை", str(ex)[:110])

    # 5b85. ஏற்கனவே வெளியானவற்றின் படங்கள் — பொருந்தாதவற்றை நீக்கு/மாற்று
    try:
        chg = 0
        for x in feed[:120]:
            if str(x.get("published_at", ""))[:10] != today:
                continue
            im = x.get("image") or {}
            if not im.get("url"):
                continue
            q = (x.get("image_query") or "").strip()
            per = (x.get("person_en") or "").strip()
            u = (im.get("url") or "").lower()
            keep = True
            if per:
                keep = ("wikipedia" in u or "wikimedia" in u)
            elif im.get("symbolic") and q:
                keep = image_matches(im, q)
            elif not q:
                keep = ("wikipedia" in u or "wikimedia" in u or "gov.in" in u)
            if not keep:
                x["image"] = place_image(x.get("headline")) or (pick_image({"items": []}, x) if q else None)
                chg += 1
        if chg:
            print(f"[image] {chg} பொருந்தாத படம் மாற்றப்பட்டது")
    except Exception as ex:
        print("[image] சுத்தப்படுத்தல் பிழை", str(ex)[:110])

    # 5b9. சந்தை நிலவரம் — தங்கம், வெள்ளி, சென்செக்ஸ், நிஃப்டி, டாலர்
    try:
        ms = market_snapshot(load_json(DATA / "market.json", {}))
        if ms:
            save_json(DATA / "market.json", ms)
            print(f"[market] தங்கம் 22K ₹{ms.get('gold22','—')} · சென்செக்ஸ் {ms.get('sensex','—')}")
        else:
            print("[market] தரவு கிடைக்கவில்லை")
    except Exception as ex:
        print("[market] பிழை", str(ex)[:110])

    # 5c. வானிலை — open-meteo (இலவசம், key தேவையில்லை); சென்னை + 4 நகரங்கள்
    try:
        cities = {"சென்னை": (13.08, 80.27), "கோயம்புத்தூர்": (11.02, 76.97), "மதுரை": (9.93, 78.12),
                  "திருச்சி": (10.79, 78.70), "சேலம்": (11.66, 78.15)}
        wx = {}
        for name, (la, lo) in cities.items():
            r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=15, params={
                "latitude": la, "longitude": lo, "timezone": "Asia/Kolkata", "forecast_days": 1,
                "current": "temperature_2m,weather_code", "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"}).json()
            wx[name] = {"now": round(r["current"]["temperature_2m"]), "code": r["current"]["weather_code"],
                        "max": round(r["daily"]["temperature_2m_max"][0]), "min": round(r["daily"]["temperature_2m_min"][0]),
                        "rain": r["daily"]["precipitation_probability_max"][0]}
        save_json(DATA / "weather.json", {"updated": datetime.now(IST).isoformat(timespec="minutes"), "cities": wx})
        print("[weather] புதுப்பிக்கப்பட்டது")
    except Exception as ex:
        print("[weather] பிழை", ex)

    # 5d. அறிவிப்புகள்
    try:
        brief_item = None
        b = load_json(DATA / "brief.json", {})
        if b.get("date") == today and state.get("push_brief_day") != today and now.hour >= 6:
            brief_item = {"title": f"இன்றைய 60 நொடி — {len(b.get('headlines', []))} செய்திகள்",
                          "body": (b.get("headlines") or [""])[0][:140], "url": "./#home", "tag": "brief"}
            state["push_brief_day"] = today
        if push_items or brief_item:
            send_push(push_items, brief_item)
    except Exception as ex:
        print("[push] பிழை", str(ex)[:120])

    # 5d2. படம் இல்லாத இன்றைய செய்திகளுக்கு குறியீட்டுப் படம்
    try:
        filled = 0
        for x in feed[:80]:
            if str(x.get("published_at", ""))[:10] == today and not (x.get("image") or {}).get("url") and filled < 30:
                if (x.get("person_en") or "").strip():
                    continue                      # நபர் செய்தி — தவறான படம் வேண்டாம்
                qq = (x.get("image_query") or "").strip()
                im = (commons_image(qq) or stock_image("", qq)) if qq else None
                if im:
                    im["symbolic"] = True; x["image"] = im; filled += 1
        if filled:
            print(f"[image] {filled} குறியீட்டுப் படங்கள் சேர்க்கப்பட்டன")
    except Exception as ex:
        print("[image] பிழை", str(ex)[:120])

    # 5e0. image_query இல்லாமல் சேர்க்கப்பட்ட பொதுப் படங்களை நீக்கு (பொருந்தாதவை)
    try:
        STOCKY = ("unsplash", "pexels", "pixabay", "openverse", "flickr", "metmuseum",
                  "nasa.gov", "si.edu", "artic.edu", "rijksmuseum", "loc.gov")
        drop = 0
        for x in feed:
            if (x.get("person_en") or "").strip() and (x.get("image") or {}).get("url"):
                u2 = (x["image"]["url"] or "").lower()
                if "wikipedia" not in u2 and "wikimedia" not in u2:
                    x["image"] = None; drop += 1     # நபர் செய்திக்குத் தவறான படம்
                    continue
            im = x.get("image") or {}
            u = (im.get("url") or "").lower()
            if u and any(h in u for h in STOCKY) and not (x.get("image_query") or "").strip():
                x["image"] = None; drop += 1        # பொருந்தாத பொதுப் படம்
        if drop:
            print(f"[image] {drop} பொருந்தாத பொதுப் படங்கள் நீக்கப்பட்டன")
    except Exception:
        pass

    # 5e. பாதுகாப்பற்ற படங்களை நீக்கு (பழைய செய்திகளிலிருந்தும்)
    removed = 0
    for x in feed:
        im = x.get("image")
        if im and im.get("url"):
            u = im["url"]
            if not _safe_host(u) and not im.get("license"):
                x["image"] = None; removed += 1
    if removed:
        print(f"[image] {removed} காப்புரிமைப் படங்கள் நீக்கப்பட்டன")

    # 6. save
    feed = dedupe_feed(feed, today)
    feed = feed[:300]
    save_json(FEED_FILE, feed)
    save_json(PENDING_FILE, pending)
    state["seen"] = list(seen)[-5000:]
    state["day_count"] = {k: v for k, v in state.get("day_count", {}).items() if k >= (now - timedelta(days=2)).strftime("%Y-%m-%d")}
    save_json(STATE_FILE, state)
    # துறை வாரியாக தனிக் கோப்புகள் (ஆப் வேகத்திற்கு)
    for t in TOPIC_TA:
        save_json(NEWS_DIR / f"{t}.json", [s for s in feed if s["topic"] == t][:60])
    # இதழ் காப்பகம் — இன்றைய இதழ் தனிக் கோப்பாக (நிரந்தரம்)
    try:
        ISSUES = DATA / "issues"; ISSUES.mkdir(parents=True, exist_ok=True)
        todays = [x for x in feed if x.get("published_at", "").startswith(today)]
        save_json(ISSUES / f"{today}.json", todays)
        idx = sorted({f.stem for f in ISSUES.glob("20*.json")}, reverse=True)   # நிரந்தரக் காப்பகம்
        save_json(ISSUES / "index.json", [{"date": d0, "count": len(load_json(ISSUES / f"{d0}.json", []))} for d0 in idx])
    except Exception as ex:
        print("[issues] பிழை", ex)

    # பழைய ஆடியோ சுத்தம் (30 நாள்)
    cutoff = time.time() - 30 * 86400
    for f in AUDIO_DIR.glob("*.mp3"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
    print(f"[done] feed {len(feed)} · pending {len(pending)} · எழுதியவை {written}")

if __name__ == "__main__":
    main()
