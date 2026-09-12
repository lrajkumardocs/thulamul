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
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "60"))
MIN_SCORE = int(os.environ.get("MIN_SCORE", "6"))               # இதற்குக் குறைவானவை எழுதப்படாது
TTS_VOICE = os.environ.get("TTS_VOICE", "ta-IN-PallaviNeural")   # Microsoft Edge இலவச தமிழ் குரல் (ஆண்: ta-IN-ValluvarNeural)
AUTO_PUBLISH_MIN_CONFIDENCE = 0.3

THIN = {"health", "agri", "jobs", "court", "spirit", "cinema", "sports", "tech"}   # தினமும் குறைந்தது 1 உறுதி
TOPIC_TA = {"tn": "தமிழ்நாடு", "india": "இந்தியா", "world": "உலகம்", "economy": "பொருளாதாரம்",
            "tech": "தொழில்நுட்பம்", "sports": "விளையாட்டு", "cinema": "சினிமா",
            "jobs": "வேலை · தேர்வு", "court": "நீதிமன்றம்", "assembly": "சட்டமன்றம்",
            "health": "சுகாதாரம்", "govt": "அரசு அறிவிப்புகள்"}

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
def cluster(items, threshold=0.28):
    """ஒரே நிகழ்வைப் பற்றிய items-ஐ இணைக்கும் (தலைப்பு+உரை சொற்கள் Jaccard)."""
    clusters = []
    for it in items:
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

def eligible(c):
    """வெளியீட்டுத் தகுதி: official ஒன்று போதும்; media என்றால் 2 தனித்த மூலங்கள்."""
    grades = {i["grade"] for i in c["items"]}
    names = {i["source"] for i in c["items"]}
    if "official" in grades:
        return True, []
    if len(names) >= 2:
        return True, []
    return True, ["single_source"]   # வெளியிடலாம், ஆனால் flag → Telegram ஒப்புதல்

# ---------------------------------------------------------------- 3. write (Claude)

FILLER_TOPICS = {
    "health": "பருவகால நோய், தடுப்பு, ஊட்டச்சத்து, சித்த/ஆயுர்வேத பொது அறிவு, அரசு சுகாதாரத் திட்டங்கள்",  # ஆன்மீகம்/விவசாயம் இப்போது வாரமலரில்
}

def write_filler(client, topic, today, now):
    """செய்தி இல்லாத பக்கத்திற்கு ஒரு பொது அறிவுக் கட்டுரை (evergreen)."""
    sysmsg = (f"நீ துலாமுள் தமிழ் நாளிதழின் {TOPIC_TA.get(topic, topic)} பக்க எழுத்தாளர். இன்று இந்தப் பக்கத்தில் செய்தி குறைவு. "
              f"வாசகருக்குப் பயன்படும் ஒரு பொது அறிவுக் கட்டுரையை எழுது. பொருள்: {FILLER_TOPICS.get(topic,'')}. "
              "இது செய்தி அல்ல — நிலையான பயனுள்ள தகவல். உண்மைகள் மட்டும்; சந்தேகமான கூற்று வேண்டாம். "
              "மருத்துவ உத்தரவாதம், முதலீட்டு ஆலோசனை தராதே. "
              'JSON மட்டும், code fence இல்லை: {"headline":"தலைப்பு 6–12 சொல்","lines":["5 வாக்கியம் — ஒவ்வொன்றும் முற்றுப்புள்ளியில் முடிய வேண்டும்"],"closing":"ஒரு வரி முடிவு","tags":["2 சொல்"]}')
        
    try:
        msg = client.messages.create(model=MODEL, max_tokens=1500, system=sysmsg,
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
        msg = client.messages.create(model=MODEL_FAST, max_tokens=2000, system=sysmsg,
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
        system=prompt.replace("{{TODAY}}", today),
        messages=[{"role": "user", "content": f"துறை குறிப்பு: {c['topic_hint']}\n\n{src_text}"}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    return parse_json(client, raw)

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

def pick_image(c, story=None):
    """படம் — தவறான படம் வருவதைவிட படமே இல்லாதது மேல்.
    1) அரசுத் தளப் படம்  2) நபர் செய்தி → அந்த நபரின் விக்கிப் படம் மட்டும்
    3) பொருள் செய்தி → image_query-க்கு commons/stock. பொருந்தாவிட்டால் None."""
    for i in c["items"]:
        u = i.get("image") or ""
        if u and _safe_host(u):
            return {"url": u, "credit": i["source"], "license": "அரசு / திறந்த உரிமம்"}
    if not story:
        return None

    person = (story.get("person_en") or "").strip()
    if person:
        # நபர் செய்தி — அவரது படம் கிடைத்தால் மட்டும்; இல்லையெனில் படம் இல்லை
        im = wiki_image(person, "en") or wiki_image(person, "ta")
        if im and person.split()[0].lower() in (im.get("credit", "") + im.get("url", "")).lower():
            return im
        return None

    q = (story.get("image_query") or "").strip()
    if not q:
        return None
    im = commons_image(q) or stock_image("", q)
    if im:
        im["symbolic"] = True
        return im
    return None

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
    TOPIC_CAP = {"tn": 10, "india": 6, "world": 5, "economy": 5, "assembly": 4}
    todays_count = {}
    for x in feed:
        if str(x.get("published_at", ""))[:10] == today and x.get("status") == "published":
            todays_count[x.get("topic")] = todays_count.get(x.get("topic"), 0) + 1
    api_dead = False
    scores = triage(client, clusters) if clusters else {}
    if scores:
        scored = [(scores.get(n, 5), n, c) for n, c in enumerate(clusters)]
        keep = [x for x in scored if x[0] >= MIN_SCORE]
        # ஒவ்வொரு பக்கத்திற்கும் குறைந்தபட்ச இடம் — பக்கம் காலியாகக் கூடாது
        PAGE_MIN = {"tn": 6, "india": 4, "world": 3, "economy": 3, "court": 3, "govt": 4,
                    "jobs": 3, "tech": 3, "health": 3, "cinema": 3, "sports": 3, "assembly": 2}
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
        keep.sort(key=lambda x: -x[0])
        print(f"[triage] {len(clusters)} → {len(keep)} (முக்கியம் + பக்க ஒதுக்கீடு)")
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
            mark_seen(c); continue
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
        save_json(FEED_FILE, feed[:300]); save_json(PENDING_FILE, pending)
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
            for t in FILLER_TOPICS:
                todays = [x for x in feed if x.get("topic") == t and str(x.get("published_at", ""))[:10] == today and x["status"] == "published"]
                if len(todays) < 2 and not any(x.get("kind") == "article" for x in todays):
                    art = write_filler(client, t, today, now)
                    if art:
                        art["image"] = stock_image("", {"health":"healthy food india","agri":"paddy field farmer india","spirit":"temple gopuram tamil nadu"}.get(t, ""))
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
                msg = client.messages.create(model=MODEL, max_tokens=3000, system=jp, messages=[{"role": "user", "content": src_text}])
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
        if malar.get("week") == week and malar.get("v", 0) < 11 and not api_dead:
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
        elif malar.get("week") != week and now.weekday() == 6 and not api_dead:   # ஞாயிறு மட்டும் — புதிய இதழ்
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
            mm2 = mal.build(client, MODEL, week, today, issue, dates_ta, done, done_heroes, telegram)
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
            msg = client.messages.create(model=MODEL, max_tokens=3000, system=ep, messages=[{"role": "user", "content": src}])
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
