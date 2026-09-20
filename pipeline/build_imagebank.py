"""
துலாமுள் — AI படக் களஞ்சியம் (ஒரு முறை உருவாக்கம்)

பொதுவான துறைகளுக்கு (நீதிமன்றம், பொருளாதாரம், சட்டம் ஒழுங்கு, சுகாதாரம், வேலை…)
விக்கிமீடியாவில் பொருத்தமான படம் கிடைப்பதில்லை. அதற்காக முன்கூட்டியே
யதார்த்தமான AI படங்களை உருவாக்கி `data/bank/` இல் சேமிக்கிறோம்.

ஓட்ட முறை (ஒரு முறை மட்டும்):
    GEMINI_API_KEY=... python pipeline/build_imagebank.py
    GEMINI_API_KEY=... python pipeline/build_imagebank.py --only court crime   # சில துறை மட்டும்
"""
import os, io, json, time, base64, argparse
from pathlib import Path
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "bank"
IDX = ROOT / "data" / "bank_index.json"
W = 1100

STYLE = ("Realistic editorial photograph, natural daylight, documentary news style, "
         "shallow depth of field, South Indian / Tamil Nadu setting where people appear — "
         "medium-to-dark brown skin, Tamil features, local clothing. "
         "No recognisable real person. "
         "ABSOLUTELY NO TEXT: no words, letters, numbers, signage or watermarks anywhere.")

BANK = {
 "court": [
  "Exterior of a colonial-era South Indian high court building with red brick and domes, empty steps",
  "Wooden judge's gavel resting on a bench in an empty courtroom, warm light",
  "Bronze statue of the blindfolded lady of justice holding scales, plain background",
  "Stacks of tied legal case files in cloth wrappers on a wooden desk",
  "Empty courtroom interior with wooden benches and a raised bench, morning light",
  "A lawyer's black coat and white bands hanging on a stand beside law books",
  "Row of thick law volumes on a shelf, close-up, warm tone",
  "Brass scales of justice on a dark wooden table, soft side light",
  "Corridor of an Indian court complex with pillars, people blurred in distance",
  "A rubber stamp and ink pad on an official register, close-up",
 ],
 "crime": [
  "Indian police patrol jeep parked on a street at dusk, no visible faces",
  "Police barricade tape across a quiet street, blurred background",
  "Empty police station reception desk with a register and an old telephone",
  "A pair of handcuffs on a wooden table, dim light",
  "Police khaki cap resting on a desk beside a file, close-up",
  "Street at night with a lone police vehicle's blue light reflected on wet road",
  "A locked iron gate of a police lock-up, corridor light",
  "CCTV camera mounted on a pole against an evening sky",
  "An investigation file with photographs face down on a desk",
  "Silhouette of a police officer on duty at a crossroads, back view",
 ],
 "economy": [
  "Indian rupee notes fanned out on a dark surface, close-up",
  "Stacks of gold bangles and coins in a jeweller's display tray",
  "Digital stock market ticker board glowing, out-of-focus numbers",
  "A vegetable market stall in Tamil Nadu with baskets of produce, vendor's hands only",
  "Rows of silver bars stacked, studio light",
  "A small shopkeeper's cash drawer with rupee notes and coins",
  "Bank counter with a queue token dispenser, blurred people",
  "Grain sacks stacked in a wholesale market warehouse",
  "Calculator, ledger and pen on a trader's desk, morning light",
  "A petrol pump nozzle and fuel dispenser display, close-up",
 ],
 "health": [
  "Hospital corridor in a South Indian government hospital, empty, daylight",
  "Stethoscope resting on a medical file on a desk",
  "Blister packs of tablets and a glass of water on a table",
  "A nurse's hands preparing a vaccine syringe, no face",
  "Ambulance parked outside a hospital entrance, evening",
  "Rows of medicine bottles on a pharmacy shelf",
  "Blood pressure monitor cuff on a patient's arm, close-up, no face",
  "A rural primary health centre building with a tiled roof",
  "Fresh vegetables and greens arranged on a banana leaf, healthy food",
  "Empty hospital bed with clean white sheets beside a window",
 ],
 "jobs": [
  "Students writing an examination in a hall, seen from behind",
  "A noticeboard with blank white sheets pinned, outdoor light",
  "Young Tamil graduates in formal shirts waiting outside an office, back view",
  "An office desk with a laptop, resume folder and pen",
  "Factory floor of an assembly line in Tamil Nadu, workers blurred",
  "A job interview table with two chairs facing each other, empty room",
  "Hands filling an application form with a pen, close-up",
  "IT office interior with rows of empty workstations",
  "A government employment exchange counter with a queue rail",
  "Construction workers at a site in safety helmets, distant view",
 ],
 "govt": [
  "A South Indian government secretariat building facade with flag pole",
  "Official file tied with red tape on a wooden government desk",
  "Empty government office with steel almirahs and stacked registers",
  "Village panchayat office building with a tiled roof and notice board",
  "A ration shop counter with sacks of rice, no faces",
  "Government bus depot with buses lined up, early morning",
  "An official seal and stamp pad on a document, close-up",
  "Queue rail outside a taluk office, people blurred",
  "Water tank and pipeline in a Tamil Nadu village",
  "Electric transformer and power lines against evening sky",
 ],
 "tech": [
  "A smartphone showing a blank screen held in hand, close-up",
  "Mobile phone tower against a clear sky",
  "Fibre optic cables and a network switch, close-up",
  "A person scanning a payment QR code at a small shop, hands only",
  "Server room with racks and indicator lights",
  "Laptop keyboard close-up in low light",
  "Satellite dish antenna against a blue sky",
  "Circuit board macro shot with components",
  "An electric two-wheeler charging at a station",
  "Drone flying over green paddy fields",
 ],
 "india": [
  "Indian Parliament building exterior, wide shot, clear sky",
  "Indian national flag fluttering against a blue sky",
  "A long-distance train crossing a rural landscape",
  "Highway with vehicles at dusk, motion blur",
  "Map of India printed on paper, close-up, no text visible",
  "A busy Indian railway platform, people blurred",
  "Indian currency and passport on a table",
  "Army truck convoy on a mountain road, distant",
  "River bridge with pillars, wide landscape",
  "Solar panel farm under bright sun",
 ],
 "world": [
  "Flags of many nations on poles against a grey sky",
  "Empty international conference hall with rows of desks",
  "Globe on a wooden desk beside a notebook",
  "Container ship at a large port, aerial view",
  "Airport runway with a plane taking off at dawn",
  "City skyline of a foreign metropolis at dusk",
  "Empty United Nations style assembly chamber",
  "Passport and boarding pass on a table",
  "Currency exchange counters with blank boards",
  "Wind turbines on a coastal hillside",
 ],
 "sports": [
  "Empty cricket stadium with floodlights at dusk",
  "Kabaddi players in action on a mud court, motion blur",
  "Silambam practitioners training with sticks at sunrise",
  "Running track lanes seen from above, empty",
  "A jallikattu arena barricade with dust in the air, no animals visible",
  "Medals hanging on a wooden stand, close-up",
  "Football on a wet grass field, close-up",
  "Hockey sticks and ball on a turf field",
  "Village wrestling ground with red soil",
  "Swimming pool lanes with clear blue water",
 ],
 "cinema": [
  "Professional film camera on a tripod on a set, lights in background",
  "Empty cinema hall with red seats and a blank screen",
  "Clapperboard held up on a film set, blank slate",
  "Studio lights and reflectors arranged on a shooting floor",
  "Rolls of film reel on a wooden table, close-up",
  "Recording studio microphone with pop filter",
  "Director's chair on an empty set",
  "Crowd of silhouetted people watching a screen in a theatre",
  "Movie projector in a dark projection room",
  "Red carpet and barricades at an event entrance, empty",
 ],
}


def gen(prompt, tries=2):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY இல்லை")
    for _ in range(tries):
        try:
            r = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-2.5-flash-image:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": STYLE + "\n\nSCENE: " + prompt}]}],
                      "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
                timeout=120).json()
            for p in r["candidates"][0]["content"]["parts"]:
                if "inlineData" in p:
                    return base64.b64decode(p["inlineData"]["data"])
                d = p.get("inline_data")
                if d and d.get("data"):
                    return base64.b64decode(d["data"])
        except Exception as ex:
            print("   பிழை", str(ex)[:80]); time.sleep(4)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--per", type=int, default=10)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    idx = json.loads(IDX.read_text(encoding="utf-8")) if IDX.exists() else {}
    topics = a.only or list(BANK)
    made = 0
    for t in topics:
        idx.setdefault(t, [])
        for n, prompt in enumerate(BANK.get(t, [])[: a.per], 1):
            name = f"{t}{n:02d}.jpg"
            fp = OUT / name
            if fp.exists():
                continue
            print(f"[{t}] {n}/{a.per} — {prompt[:52]}…")
            b = gen(prompt)
            if not b:
                continue
            im = Image.open(io.BytesIO(b)).convert("RGB")
            im = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
            im.save(fp, "JPEG", quality=84, optimize=True)
            rec = {"file": f"data/bank/{name}", "prompt": prompt}
            if rec not in idx[t]:
                idx[t].append(rec)
            made += 1
            time.sleep(2)
        IDX.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nமுடிந்தது — {made} புதிய படம். மொத்தம்: " +
          ", ".join(f"{k}:{len(v)}" for k, v in idx.items()))


if __name__ == "__main__":
    main()
