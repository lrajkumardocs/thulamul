"""
துலாமுள் — பொன்னியின் செல்வன் பாத்திரக் குறிப்புப் படங்கள் (ஒரு முறை / தேவைப்படும்போது)
comic_characters.json → Gemini → pipeline/comic_refs/<id>.png → Telegram preview
env CHARS = "all" அல்லது "nandini,kundavai" (பிடிக்காதவற்றை மட்டும் மீண்டும் உருவாக்க)
"""
import os, sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import comic

REFS = comic.REFS
CH = comic.CHARS

def sheet(c):
    parts = [{"text": CH["style_en"] + "\n\nCHARACTER REFERENCE SHEET (model sheet for a comic). "
              "Show the SAME character three times side by side on a plain cream lime-plaster background, evenly spaced: "
              "(1) full-body front view, (2) full-body three-quarter view, (3) a large head-and-shoulders close-up of the face. "
              "Identical face, hair, dress and colours in all three. Landscape composition. Absolutely no text or labels.\n\n"
              f"CHARACTER: {c['visual_en']}"}]
    return comic._gemini(parts, c["id"])

def main():
    want = os.environ.get("CHARS", "all").strip()
    ids = [c["id"] for c in CH["characters"]] if want in ("", "all") else [x.strip() for x in want.split(",") if x.strip()]
    REFS.mkdir(parents=True, exist_ok=True)
    done, fail = [], []
    for c in CH["characters"]:
        if c["id"] not in ids:
            continue
        b = sheet(c)
        if not b:
            fail.append(c["id"]); continue
        p = REFS / f"{c['id']}.png"; p.write_bytes(b); done.append(c["id"])
        comic.telegram_photo(p, f"🎨 <b>{c['name_ta']}</b> ({c['id']})\n{c['role_ta']}\n\n{c['ta']}\n\nபிடிக்கவில்லை எனில்: Actions → comic-characters → chars = <code>{c['id']}</code>")
        print("[chars] தயார்:", c["id"]); time.sleep(2)
    print(f"[chars] {len(done)} தயார் · {len(fail)} தோல்வி {fail}")

if __name__ == "__main__":
    main()
