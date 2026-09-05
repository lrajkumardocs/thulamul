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
MAX_NEW_PER_RUN = int(os.environ.get("MAX_NEW_PER_RUN", "12"))   # ஒரு ஓட்டத்தில் அதிகபட்சம் (செலவு கட்டுப்பாடு)
TTS_VOICE = os.environ.get("TTS_VOICE", "ta-IN-PallaviNeural")   # Microsoft Edge இலவச தமிழ் குரல் (ஆண்: ta-IN-ValluvarNeural)
AUTO_PUBLISH_MIN_CONFIDENCE = 0.7

TOPIC_TA = {"tn": "தமிழ்நாடு", "india": "இந்தியா", "world": "உலகம்", "economy": "பொருளாதாரம்",
            "tech": "தொழில்நுட்பம்", "sports": "விளையாட்டு", "cinema": "சினிமா", "spirit": "ஆன்மீகம்",
            "jobs": "வேலை · தேர்வு", "court": "நீதிமன்றம்", "assembly": "சட்டமன்றம்"}

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
                if pp and (time.time() - time.mktime(pp)) > 36 * 3600:
                    seen.add(iid); continue          # 36 மணிக்கு மேல் பழையது — தவிர்
                text = clean_html(e.get("summary") or e.get("description") or "")
                if hasattr(e, "content") and e.content:
                    text = clean_html(e.content[0].get("value", "")) or text
                fresh.append({
                    "id": iid, "source": src["name"], "grade": src.get("grade", "media"),
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
def write_news(client, prompt, c, today):
    src_text = "\n\n".join(
        f"[மூலம் {n+1}: {i['source']} | {i['published']} | {i['link']}]\nதலைப்பு: {i['title']}\n{i['text']}"
        for n, i in enumerate(c["items"][:4]))
    msg = client.messages.create(
        model=MODEL, max_tokens=4000,
        system=prompt.replace("{{TODAY}}", today),
        messages=[{"role": "user", "content": f"துறை குறிப்பு: {c['topic_hint']}\n\n{src_text}"}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("JSON இல்லை: " + raw[:120])
    return json.loads(raw[a:b + 1])

def validate(story):
    ok = isinstance(story.get("lines"), list) and len(story["lines"]) == 5
    ok &= bool(story.get("headline")) and bool(story.get("closing"))
    ok &= story.get("topic") in TOPIC_TA
    return ok

# ---------------------------------------------------------------- 4. audio (Edge TTS, இலவசம்)
async def _tts(text, out):
    import edge_tts
    await edge_tts.Communicate(text, TTS_VOICE, rate="-5%").save(str(out))

def make_audio(story_id, script):
    out = AUDIO_DIR / f"{story_id}.mp3"
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(asyncio.wait_for(_tts(script, out), timeout=60))   # 60 நொடிக்கு மேல் காத்திருக்காது
        return f"data/audio/{story_id}.mp3"
    except Exception as ex:
        print(f"[tts] {story_id}: பிழை {ex}")
        return None

# ---------------------------------------------------------------- 5. image (மூலப் படம் மட்டும்; இல்லையெனில் null → ஆப் துறை-அட்டை காட்டும்)
def pick_image(c):
    for i in c["items"]:
        m = re.search(r'<img[^>]+src="([^"]+)"', i.get("raw_html", "") or "")
        if m:
            return {"url": m.group(1), "credit": i["source"]}
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
    for p in pending:
        d = decisions.get(p["id"])
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
    def mark_seen(c):
        for i in c["items"]:
            seen.add(i["id"])
    for c in clusters:
        if written >= MAX_NEW_PER_RUN or time.time() - t_start > 15 * 60:
            continue                      # அடுத்த ஓட்டத்தில் எடுக்கும்; seen-ல் சேர்க்காது
        ok, extra_flags = eligible(c)
        if not ok:
            mark_seen(c); continue
        try:
            story = write_news(client, prompt, c, today)
        except Exception as ex:
            print("[claude] பிழை", ex); continue   # பிழை → அடுத்த ஓட்டத்தில் மீண்டும் முயற்சி
        if not validate(story):
            print("[validate] தவறான வடிவம், தவிர்க்கப்பட்டது"); mark_seen(c); continue
        mark_seen(c)
        written += 1
        sid = c["items"][0]["id"]
        story["id"] = sid
        story["flags"] = sorted(set(story.get("flags", []) + extra_flags))
        story["topic_ta"] = TOPIC_TA[story["topic"]]
        story["published_at"] = datetime.now(IST).isoformat(timespec="minutes")
        story["links"] = [i["link"] for i in c["items"]]
        story["image"] = pick_image(c)
        story["audio"] = make_audio(sid, story["headline"] + ". " + " ".join(story["lines"]) + " " + story["closing"])
        story["created_ts"] = time.time()

        hold = bool(story["flags"]) or story.get("confidence", 1) < AUTO_PUBLISH_MIN_CONFIDENCE
        if hold:
            story["status"] = "pending"; pending.append(story)
            telegram(f"⚖️ <b>சரிபார்க்க</b> [{', '.join(story['flags']) or 'குறைந்த நம்பிக்கை'}]\n"
                     f"<b>{story['headline']}</b>\n" + "\n".join(story["lines"]) +
                     f"\n\nமூலம்: {', '.join(s['name'] for s in story['sources'])}\n"
                     f"பதில்: <code>✔ {sid}</code> அல்லது <code>✘ {sid}</code>")
            print("[hold]", story["headline"])
        else:
            story["status"] = "published"; feed.insert(0, story)
            print("[publish]", story["headline"])
        save_json(FEED_FILE, feed[:300]); save_json(PENDING_FILE, pending)
        state["seen"] = list(seen)[-5000:]; save_json(STATE_FILE, state)   # ஒவ்வொன்றுக்கும் உடனே சேமி

    # 6. save
    feed = feed[:300]
    save_json(FEED_FILE, feed)
    save_json(PENDING_FILE, pending)
    state["seen"] = list(seen)[-5000:]
    save_json(STATE_FILE, state)
    # துறை வாரியாக தனிக் கோப்புகள் (ஆப் வேகத்திற்கு)
    for t in TOPIC_TA:
        save_json(NEWS_DIR / f"{t}.json", [s for s in feed if s["topic"] == t][:60])
    # பழைய ஆடியோ சுத்தம் (30 நாள்)
    cutoff = time.time() - 30 * 86400
    for f in AUDIO_DIR.glob("*.mp3"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
    print(f"[done] feed {len(feed)} · pending {len(pending)} · எழுதியவை {written}")

if __name__ == "__main__":
    main()
