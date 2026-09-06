"""
துலாமுள் — செய்தி இயந்திரம் (Session 1)
ஓட்டம்: மூலங்கள் (RSS) → புதியவை → ஒரே நிகழ்வு இணைப்பு → Claude 5-வரி → flag → ஆடியோ → data/ JSON

GitHub Actions ஒவ்வொரு 30 நிமிடமும் இதை ஓட்டும். மனிதன் தேவைப்படுவது flag ஆனவற்றுக்கு மட்டும் (Telegram).
"""
import os, re, json, hashlib, asyncio, time, socket
socket.setdefaulttimeout(20)   # எந்த இணைய அழைப்பும் 20 நொடிக்கு மேல் காத்திருக்காது
from datetime import datetime, timezone, timedelta
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
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
MAX_NEW_PER_RUN = int(os.environ.get("MAX_NEW_PER_RUN", "8"))    # ஒரு ஓட்டத்தில் அதிகபட்சம்
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "80"))         # ஒரு நாளில் அதிகபட்சம் (செலவு கட்டுப்பாடு)
TTS_VOICE = os.environ.get("TTS_VOICE", "ta-IN-PallaviNeural")   # Microsoft Edge இலவச தமிழ் குரல் (ஆண்: ta-IN-ValluvarNeural)
AUTO_PUBLISH_MIN_CONFIDENCE = 0.3

THIN = {"health", "agri", "jobs", "court", "spirit", "cinema", "sports", "tech"}   # தினமும் குறைந்தது 1 உறுதி
TOPIC_TA = {"tn": "தமிழ்நாடு", "india": "இந்தியா", "world": "உலகம்", "economy": "பொருளாதாரம்",
            "tech": "தொழில்நுட்பம்", "sports": "விளையாட்டு", "cinema": "சினிமா", "spirit": "ஆன்மீகம்",
            "jobs": "வேலை · தேர்வு", "court": "நீதிமன்றம்", "assembly": "சட்டமன்றம்",
            "health": "சுகாதாரம்", "agri": "விவசாயம்"}

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
        "ABSOLUTELY NO TEXT: no words, letters, numbers, captions, signage text, labels, logos or speech bubbles anywhere in the image. "
        "Any board, sign, poster, file or screen in the scene must be completely blank or show only abstract squiggles.\n"
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

def write_news(client, prompt, c, today):
    src_text = "\n\n".join(
        f"[மூலம் {n+1}: {i['source']} | {i['published']} | {i['link']}]\nதலைப்பு: {i['title']}\n{i['text'][:1500]}"
        for n, i in enumerate(c["items"][:3]))
    msg = client.messages.create(
        model=MODEL, max_tokens=3000,
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
    await edge_tts.Communicate(text, TTS_VOICE, rate="-5%").save(str(out))

TTS_STATE = {"edge_failed": 0}
def speakable(text):
    """ஆடியோவுக்கு உரையைச் சீரமை — நிறுத்தற்குறி, இடைவெளி, சுருக்கங்கள்."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = t.replace("—", ", ").replace("–", ", ").replace("·", ", ").replace("|", ", ")
    t = re.sub(r"\(([^)]{1,40})\)", r", \1,", t)          # அடைப்புக்குறி → இடைநிறுத்தம்
    t = t.replace("₹", " ரூபாய் ").replace("%", " சதவீதம் ")
    t = re.sub(r"([.!?])(?=\S)", r"\1 ", t)                # புள்ளிக்குப் பின் இடைவெளி
    t = re.sub(r"([^.!?])$", r"\1.", t)                    # முடிவில் புள்ளி
    t = re.sub(r"\s*([,.])\s*", r"\1 ", t)
    return t.strip()
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
        gTTS(script, lang="ta").save(str(out))
        return f"data/audio/{story_id}.mp3"
    except Exception as ex:
        print(f"[tts-gtts] {story_id}: {str(ex)[:80]}")
        return None

# ---------------------------------------------------------------- 5. image (மூலப் படம் மட்டும்; இல்லையெனில் null → ஆப் துறை-அட்டை காட்டும்)
def pick_image(c):
    for i in c["items"]:
        if i.get("img"):
            return {"url": i["img"], "credit": i["source"]}
    return None

# ---------------------------------------------------------------- 6. telegram
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
        if re.match(r"^(✘|✗|no|வேண்டாம்)\s*editorial", t, re.I):
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
    boosted = set()
    def prio(c):
        t = c["topic_hint"]
        if t in THIN and t not in today_topics and t not in boosted:
            boosted.add(t); return (0, 0)
        return (1, -len(c["items"]))          # பல மூலங்கள் = முக்கியம்
    clusters.sort(key=prio)
    def mark_seen(c):
        for i in c["items"]:
            seen.add(i["id"])
    push_items = []
    day_count = state.get("day_count", {}).get(today, 0)
    api_dead = False
    for c in clusters:
        if api_dead or written >= MAX_NEW_PER_RUN or day_count + written >= MAX_PER_DAY or time.time() - t_start > 15 * 60:
            continue                      # அடுத்த ஓட்டத்தில் எடுக்கும்; seen-ல் சேர்க்காது
        ok, extra_flags = eligible(c)
        if not ok:
            mark_seen(c); continue
        try:
            story = write_news(client, prompt, c, today)
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
        story["image"] = pick_image(c)
        story["audio"] = make_audio(sid, ". ".join([story["headline"].rstrip(".")] + [l.rstrip(".") for l in story["lines"]] + [story["closing"].rstrip(".")]) + ".")
        story["created_ts"] = time.time()

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
            story["status"] = "published"; feed.insert(0, story)
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

    # 5b1. இன்றைய வேலை அறிவிப்புகள் — தினமும் ஒரு தொகுப்பு (8:00-க்குப் பின், ஒரு முறை)
    try:
        jd = load_json(DATA / "jobs_digest.json", {})
        if now.hour >= 8 and jd.get("date") != today and not api_dead:
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

    # 5b2. வாரமலர் — ஞாயிறு (அல்லது இந்த வாரத்திற்கு இல்லையெனில்) ஒரு முறை
    try:
        week = now.strftime("%G-W%V")
        malar = load_json(DATA / "malar.json", {})
        if malar.get("week") != week and (now.weekday() == 6 or not malar) and not api_dead:
            mon = now - timedelta(days=now.weekday()); dates = ", ".join((mon + timedelta(days=i)).strftime("%m-%d") for i in range(7))
            mp = (ROOT / "pipeline/prompts/malar.md").read_text(encoding="utf-8").replace("{{WEEK}}", week).replace("{{TODAY}}", today).replace("{{DATES}}", dates)
            wk_cut = (now - timedelta(days=7)).isoformat()
            wk = [x for x in feed if x.get("published_at", "") > wk_cut and x.get("status") == "published"][:40]
            wk_txt = "\n".join(f"[{x['topic_ta']}] {x['headline']}" for x in wk) or "(செய்திகள் இல்லை)"
            msg = client.messages.create(model=MODEL, max_tokens=8000, system=mp,
                messages=[{"role": "user", "content": "சென்ற வாரத்தின் செய்தித் தலைப்புகள்:\n" + wk_txt + "\n\nஇவற்றிலிருந்து 'சென்ற வார உலகம்' பகுதியை எழுது; மற்ற பகுதிகளை உன் அறிவிலிருந்து எழுது."}])
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            m = parse_json(client, raw); m["week"] = week; m["generated"] = today
            if m.get("song", {}).get("text"):
                m["song"]["audio"] = make_audio(f"malar_{week}", m["song"]["text"] + ". பொருள்: " + m["song"].get("meaning", ""))
            save_json(DATA / "malar.json", m); print("[malar] வாரமலர் தயார்", week)
    except Exception as ex:
        print("[malar] பிழை", ex)

    # 5b4. AI தலையங்கம் "தராசில் இன்று" + கேலிச்சித்திரம் — தினமும் 5:30-க்குப் பின் ஒரு முறை
    try:
        ed = load_json(DATA / "ai_editorial.json", {})
        todays_pub = [x for x in feed if x.get("published_at", "").startswith(today) and x["status"] == "published" and x["topic"] in ("tn", "india", "world", "economy", "court", "health", "agri", "assembly")]
        if now.hour >= 5 and ed.get("date") != today and len(todays_pub) >= 3 and not api_dead:
            src = "\n\n".join(f"[{x['topic_ta']}] {x['headline']}\n" + " ".join(x["lines"]) for x in todays_pub[:10])
            ep = (ROOT / "pipeline/prompts/editorial.md").read_text(encoding="utf-8").replace("{{TODAY}}", today)
            msg = client.messages.create(model=MODEL, max_tokens=3000, system=ep, messages=[{"role": "user", "content": src}])
            raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            e = parse_json(client, raw); e["date"] = today; e["author"] = "Mr. X"
            e["audio"] = make_audio(f"editorial_{today.replace('-', '')}", f"தராசில் இன்று. {e['title']}. {e['issue']} ஒரு தட்டு: {e['side_a']['label']}. " + " ".join(e["side_a"]["points"]) + f" மறு தட்டு: {e['side_b']['label']}. " + " ".join(e["side_b"]["points"]) + " " + e["question"])
            e["cartoon"]["image"] = make_cartoon(e["cartoon"].get("scene_en", ""), today, e["cartoon"].get("caption_ta", "")); e["cartoon_v"] = 5
            save_json(DATA / "ai_editorial.json", e); print("[editorial] தராசில் இன்று:", e["title"])
            telegram(f"⚖️ <b>தராசில் இன்று</b> — {e['title']}\n{e['question']}\n\n🖼 {e['cartoon'].get('caption_ta','')}\n{'படம் தயார்' if e['cartoon'].get('image') else 'படம் இல்லை'}\n\nதவறு என்றால் <code>✘ editorial</code>")
        elif ed.get("date") == today and (not ed.get("cartoon", {}).get("image") or ed.get("cartoon_v") != 5) and not api_dead:
            img = make_cartoon(ed.get("cartoon", {}).get("scene_en", ""), today, ed.get("cartoon", {}).get("caption_ta", ""))   # படம் மட்டும் மீண்டும்
            if img:
                ed["cartoon"]["image"] = img; ed["cartoon_v"] = 5; save_json(DATA / "ai_editorial.json", ed); print("[cartoon] படம் தயார்")
    except Exception as ex:
        print("[editorial] பிழை", str(ex)[:200])

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
        idx = sorted({f.stem for f in ISSUES.glob("20*.json")}, reverse=True)   # நிரந்தரக் காப்பகம் — நீக்கம் இல்லை
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
