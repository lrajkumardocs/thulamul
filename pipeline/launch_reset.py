"""
துலாமுள் — Launch நாள் மீட்டமைப்பு (விஜயதசமி, 20 அக்டோபர் 2026)

என்ன செய்கிறது:
  • இதழ் எண் → 1 (தினசரி + வாரமலர்)
  • காமிக்ஸ் → காட்சி 1-லிருந்து மீண்டும் தொடங்கும்
  • சோதனைக் காலச் செய்திகள் → காப்பகத்தில் (அழிக்கப்படுவதில்லை)
  • வாரமலர் — காலம் சாராத பகுதிகள் மீண்டும் பயன்படுத்தப்படும் (LAUNCH_REUSE=1)
  • சோதனைக் காலக் கேலிச்சித்திரங்கள்/காமிக்ஸ் படங்கள் data/-ல் அப்படியே இருக்கும்

ஓட்ட முறை (launch-க்கு ஒரு நாள் முன்):
    python pipeline/launch_reset.py --date 2026-10-20
பிறகு GitHub secrets/vars-ல் LAUNCH_REUSE=1 சேர்த்து ஒரு Run.
"""
import json, shutil, argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _j(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _s(p, o):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")


def reset(launch_date):
    # 1. சோதனைச் செய்திகள் → காப்பகம்
    feed = _j(DATA / "feed.json", [])
    if feed:
        _s(DATA / "feed_testphase.json", feed)
        _s(DATA / "feed.json", [])
        print(f"[reset] {len(feed)} சோதனைச் செய்திகள் காப்பகத்தில்")

    # 2. நாள்/இதழ் நிலை
    st = _j(DATA / "state.json", {})
    st["day_count"] = {}
    st["launch_date"] = launch_date
    st.pop("push_brief_day", None)
    _s(DATA / "state.json", st)
    print(f"[reset] இதழ் தொடக்கம் {launch_date}")

    # 3. காமிக்ஸ் → காட்சி 1
    cs = _j(DATA / "comic_state.json", {})
    if cs:
        _s(DATA / "comic_state_testphase.json", cs)
    _s(DATA / "comic_state.json", {"global_day": 0, "arc_index": 0, "beat_index": 0,
                                   "last_date": "", "launch_date": launch_date,
                                   "story_so_far": "", "recent": []})
    idx = _j(DATA / "comic_index.json", [])
    if idx:
        _s(DATA / "comic_index_testphase.json", idx)
    _s(DATA / "comic_index.json", [])
    print("[reset] காமிக்ஸ் காட்சி 1-லிருந்து")

    # 4. வாரமலர் — காப்பகம் தயார், தற்போதையது நீக்கம்
    m = _j(DATA / "malar.json", {})
    if m:
        _s(DATA / "malar_testphase.json", m)
    _s(DATA / "malar.json", {})
    _s(DATA / "malar_reused.json", [])
    arc = _j(DATA / "malar_archive.json", [])
    print(f"[reset] வாரமலர் காப்பகம் {len(arc)} வாரம் — மீண்டும் பயன்படுத்தத் தயார்")

    # 5. தலையங்கம் / கேலிச்சித்திரம் — புதிதாக
    for f in ("ai_editorial.json", "brief.json", "jobs.json", "rasi.json"):
        p = DATA / f
        if p.exists():
            shutil.copy(p, DATA / f.replace(".json", "_testphase.json"))
            _s(p, {})
    print("[reset] தலையங்கம்/brief/வேலை/ராசி — புதிதாக")
    print("\nமுடிந்தது. LAUNCH_REUSE=1 சேர்த்து Run ஓட்டவும்.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-20")
    reset(ap.parse_args().date)
