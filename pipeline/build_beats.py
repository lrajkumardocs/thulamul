"""
துலாமுள் — 942 நாட்களுக்கும் நிகழ்வுகளை முன்பே பிரித்து நிரந்தரமாகப் பூட்டும் கருவி (ஒரு முறை).

comic_story.json (38 பகுதி) → ஒவ்வொரு பகுதியையும் Claude அதன் நாள் எண்ணிக்கைக்கு ஏற்பப் பிரிக்கும்
→ pipeline/comic_beats.json  {"b1a01": ["நாள் 1 நிகழ்வு", "நாள் 2 நிகழ்வு", ...], ...}

ஒரு முறை ஓடியபின் அது பூட்டப்பட்டது: ஏற்கெனவே உள்ள பகுதிகளை மீண்டும் எழுதாது.
மீண்டும் எழுத வேண்டுமெனில் env ARCS="b1a01,b1a02" (அல்லது "all" = எல்லாம் மீண்டும்).
தினசரிக் காமிக்ஸ் இதிலிருந்து அன்றைய ஒரு வரியை மட்டும் எடுத்து 4 பலகையாக்கும் — கதைக் குழப்பம் இல்லை.
"""
import os, re, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import comic
from anthropic import Anthropic

PIPE = comic.PIPE
BEATS_FILE = PIPE / "comic_beats.json"
STORY = comic.STORY
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

SYS = """நீ கல்கியின் "பொன்னியின் செல்வன்" நாவலைத் தினசரிக் காமிக்ஸாக மாற்றும் திட்டமிடுபவன்.
உனக்குத் தரப்படுவது: ஒரு கதைப் பகுதியின் சுருக்கம், அதன் இடங்கள், பாத்திரங்கள், மற்றும் N (இப்பகுதி எத்தனை நாள் ஓட வேண்டும்).

வேலை: அந்தச் சுருக்கத்தை **சரியாக N நாட்களாக** வரிசையாகப் பிரி. ஒவ்வொரு நாளும் ஒரு காமிக்ஸ் பக்கம் (4 பலகை) ஆகும்.

விதிகள்:
1. சுருக்கத்தில் உள்ள நிகழ்வுகள் அனைத்தும் வரிசை மாறாமல் வர வேண்டும்; புதிய கதை சேர்க்கக் கூடாது; நாவலுக்கு முரணாக எதுவும் கூடாது.
2. ஒரு நாளுக்கு ஒரு சிறு நிகழ்வு — 4 பலகையில் சொல்லக்கூடிய அளவு. மிகப் பெரிய நிகழ்வை இரண்டு மூன்று நாட்களாகப் பிரி (எ.கா. "விருந்து தொடங்குகிறது" / "ஒட்டுக் கேட்கிறான்" / "பிடிபடும் அபாயம்").
3. N நாட்களை நிரப்ப நீட்டிக்க வேண்டியிருந்தால் — நாவலின் சுவைக்கு ஏற்ற உரையாடல், விவரணை, பயணக் காட்சி, பாத்திர எண்ணங்கள் ஆகியவற்றால் நிரப்பு; வெற்று மீள்சொல்லல் கூடாது.
4. ஒவ்வொரு வரியும் தமிழில், 12–25 சொற்கள்; "யார், எங்கே, என்ன நடக்கிறது" என்பது தெளிவாக இருக்க வேண்டும்.
5. கடைசி நாள் அந்தப் பகுதியின் இறுதி நிகழ்வோடு முடிய வேண்டும்.

வெளியீடு: JSON வரிசை (array) மட்டும், சரியாக N உறுப்புகள். வேறு எந்த எழுத்தும் வேண்டாம்.
["நாள் 1 …", "நாள் 2 …", ...]"""


def expand(client, arc):
    n = arc["days"]
    user = (f"பாகம் {arc['book']} · பகுதி «{arc['title_ta']}» · N = {n}\n"
            f"இடங்கள்: {arc.get('places', '')}\n"
            f"முக்கியப் பாத்திரங்கள்: {', '.join(arc.get('chars', []))}"
            + (f" · துணை: {', '.join(arc.get('extras', []))}" if arc.get("extras") else "") +
            f"\n\nசுருக்கம்:\n{arc['synopsis_ta']}\n\nசரியாக {n} வரிகள் கொண்ட JSON array தா.")
    for attempt in (1, 2, 3):
        msg = client.messages.create(model=MODEL, max_tokens=8000, system=SYS,
                                     messages=[{"role": "user", "content": user if attempt == 1 else
                                                user + f"\n\n(முந்தைய முயற்சியில் எண்ணிக்கை தவறு. சரியாக {n} வரிகள் வேண்டும்.)"}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        try:
            arr = json.loads(raw[raw.index("["):raw.rindex("]") + 1])
        except Exception as ex:
            print("  JSON பிழை", str(ex)[:80]); continue
        arr = [str(x).strip() for x in arr if str(x).strip()]
        if len(arr) == n:
            return arr
        print(f"  எண்ணிக்கை {len(arr)} ≠ {n} — மீண்டும்")
        if attempt == 3:                                   # கடைசி முயற்சி: வெட்டு அல்லது கடைசியை மீண்டும்
            return (arr + [arr[-1]] * n)[:n] if arr else None
    return None


def main():
    want = os.environ.get("ARCS", "").strip()
    beats = comic._j(BEATS_FILE, {})
    client = Anthropic(timeout=300, max_retries=2)
    todo = [a for a in STORY["arcs"] if (want == "all" or (want and a["id"] in [x.strip() for x in want.split(",")])
                                         or (not want and a["id"] not in beats))]
    print(f"[beats] செய்ய வேண்டியவை: {len(todo)} பகுதி")
    ok = 0
    for a in todo:
        print(f"[beats] {a['id']} «{a['title_ta']}» · {a['days']} நாள்")
        arr = expand(client, a)
        if not arr:
            print("  தோல்வி"); continue
        beats[a["id"]] = arr; ok += 1
        comic._save(BEATS_FILE, beats)                     # ஒவ்வொன்றும் உடனே சேமிப்பு
        time.sleep(1)
    total = sum(len(v) for v in beats.values())
    print(f"[beats] {ok} பகுதி முடிந்தது · மொத்தம் {len(beats)}/{len(STORY['arcs'])} பகுதி · {total} நாள் பூட்டப்பட்டது")
    comic.telegram(f"📋 <b>கதைத் திட்டம்</b>\n{len(beats)}/{len(STORY['arcs'])} பகுதி · {total} நாள் பூட்டப்பட்டது.")


if __name__ == "__main__":
    main()
