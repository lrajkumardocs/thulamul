"""
துலாமுள் — AI படக் களஞ்சியம் (ஒரு முறை உருவாக்கம்)

பொதுவான துறைகளுக்கு (நீதிமன்றம், பொருளாதாரம், சட்டம் ஒழுங்கு, சுகாதாரம், வேலை…)
விக்கிமீடியாவில் பொருத்தமான படம் கிடைப்பதில்லை. அதற்காக முன்கூட்டியே
யதார்த்தமான AI படங்களை உருவாக்கி `data/bank/` இல் சேமிக்கிறோம்.

விதிகள்:
  • மனித முகம் எங்கும் கூடாது (கை, முதுகுப்புறம், தொலைவு நிழல் மட்டும்)
  • அரசு இலச்சினை / தேசிய சின்னம் கூடாது (சட்டப்படி தடை)
  • எந்த எழுத்தும் கூடாது
  • ஒவ்வொரு படத்திற்கும் தமிழ் குறிச்சொற்கள் → செய்திக்கு ஏற்ற படம் தேர்வு

ஓட்ட முறை:
    GEMINI_API_KEY=... python pipeline/build_imagebank.py
    GEMINI_API_KEY=... python pipeline/build_imagebank.py --only court crime
    GEMINI_API_KEY=... python pipeline/build_imagebank.py --per 5     # ஒரு துறைக்கு 5 மட்டும்
"""
import os, io, json, time, base64, argparse
from pathlib import Path
import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "bank"
IDX = ROOT / "data" / "bank_index.json"
W = 1100

STYLE = (
    "Realistic editorial news photograph, natural daylight, documentary style, "
    "shallow depth of field, South Indian / Tamil Nadu setting.\n"
    "RULE 1 — ZERO PEOPLE. The frame must be completely deserted. Not one person, "
    "not even far away, out of focus, in shadow, behind a window, in a doorway or at the edge "
    "of the frame. No hands, no arms, no legs, no silhouettes, no crowds. "
    "No human face may appear anywhere — not on a person, not on a statue, bust, idol, mural, "
    "painting, poster, portrait, photograph, coin, note, screen, mirror or reflection. "
    "If the scene would normally contain people, show the same place empty and still.\n"
    "RULE 2 — ZERO TEXT. No words, letters, numerals, handwriting, printed pages, signboards, "
    "name plates, book titles, screen text, labels or watermarks. Every surface, page, board "
    "and screen must be blank or too out of focus to read.\n"
    "RULE 3 — NO EMBLEMS. No national or state emblem, government crest, coat of arms, "
    "official insignia, political party symbol, company logo or brand mark.\n"
    "RULE 4 — Nothing that identifies a real named person, a real named building or a real organisation."
)


TOPIC_TA = {
    "court": "நீதிமன்றம்", "crime": "சட்டம் ஒழுங்கு", "economy": "பொருளாதாரம்",
    "health": "சுகாதாரம்", "jobs": "வேலைவாய்ப்பு", "govt": "அரசு அறிவிப்புகள்",
    "tech": "தொழில்நுட்பம்", "india": "இந்தியா", "world": "உலகம்",
    "sports": "விளையாட்டு", "cinema": "சினிமா", "edu": "கல்வி",
    "agri": "வேளாண்மை", "weather": "வானிலை / பேரிடர்", "transport": "போக்குவரத்து",
    "power": "மின்சாரம் / குடிநீர்", "local": "உள்ளாட்சி", "politics": "அரசியல் நிகழ்வு",
    "accident": "விபத்து", "fisher": "மீனவர் / கடல்", "labour": "தொழிலாளர்",
    "women": "மகளிர் / குழந்தை", "pension": "ஓய்வூதியம்", "env": "சுற்றுச்சூழல்",
    "temple": "கோயில் / திருவிழா", "space": "விண்வெளி", "defence": "பாதுகாப்பு",
}

# சில துறைகளுக்கு மட்டும் கூடுதல் விதி
STYLE_EXTRA = {
    "temple": ("EXCEPTION to Rule 1: traditional carved stone or painted stucco temple sculptures "
               "of deities may appear as part of the architecture. Still absolutely no living "
               "person, devotee, priest or worshipper anywhere in the frame."),
    "cinema": ("No film poster, no actor image, no portrait of any kind on walls, screens or hoardings — "
               "screens and hoardings must be blank."),
}

# ஒவ்வொரு உள்ளீடும்: (ஆங்கில prompt, தமிழ் குறிச்சொற்கள்)
BANK = {
 # ── நீதிமன்றம் (ஏற்கனவே உருவாக்கப்பட்டது) ──────────────────────────────
 "court": [
  ("Exterior of a colonial-era South Indian high court building with red brick, arches and domes, empty steps, no people",
   "உயர்நீதிமன்றம் நீதிமன்றம் வழக்கு தீர்ப்பு"),
  ("Wooden judge's gavel resting on a sound block on an empty bench, warm light, no people",
   "தீர்ப்பு நீதிபதி உத்தரவு வழக்கு"),
  ("A polished brass balance scale standing alone on a dark wooden table against a plain grey wall, studio light, deserted room",
   "நீதி நியாயம் தீர்ப்பு சமநிலை"),
  ("Bundles of aged buff-coloured legal papers tied with red tape, stacked in leaning piles on an empty wooden desk in a deserted office, blank pages, no writing",
   "வழக்கு கோப்பு மனு பதிவு"),
  ("Empty courtroom interior with rows of wooden benches and a raised judge's bench, morning light, no people",
   "நீதிமன்றம் விசாரணை அமர்வு"),
  ("A black advocate's gown and white neck bands hanging on a wooden coat stand in an empty whitewashed room, closed plain-bound books on a stool, no person anywhere",
   "வழக்கறிஞர் வக்கீல் வழக்கு"),
  ("Close-up of a row of thick leather-bound volumes with blank untitled spines on a wooden shelf, warm tone, plain wall behind, deserted",
   "சட்டம் தீர்ப்பு நூல் விதி"),
  ("An old brass ink stand, a closed blank ledger and a wooden gavel arranged on a dark polished desk, soft side light, empty room",
   "நீதி தீர்ப்பு நியாயம்"),
  ("Long corridor of a colonial red-brick courthouse with pointed gothic arches and a tiled floor, morning sunlight and shadows, absolutely deserted, not a single person",
   "நீதிமன்றம் வளாகம் விசாரணை"),
  ("A wooden-handled rubber stamp lying beside a round ink pad on a completely blank ruled page of an open register, close-up, empty desk, no hand, no writing",
   "பதிவு உத்தரவு ஆவணம் முத்திரை"),
 ],

 # ── சட்டம் ஒழுங்கு (கொலை 6 · கொள்ளை 6 · பாலியல் வன்கொடுமை 6 · பொது 6) ──
 "crime": [
  ("Police barricade tape stretched across a narrow residential lane at dusk, completely empty street",
   "கொலை படுகொலை குற்றம் விசாரணை"),
  ("A plain white cloth and a police cordon rope on an empty tar road at dawn, sombre mood, no people",
   "கொலை உயிரிழப்பு சடலம் விசாரணை"),
  ("Numbered yellow evidence markers placed on a concrete floor inside a cordon, no people",
   "கொலை ஆதாரம் விசாரணை குற்றம்"),
  ("A forensic evidence kit with gloves, tweezers and sample bags laid out on a dark table",
   "தடயவியல் ஆதாரம் விசாரணை"),
  ("An empty village lane at night lit by a single street lamp, long shadows, no people",
   "கொலை இரவு தாக்குதல் குற்றம்"),
  ("A police patrol jeep parked beside shuttered shops at night, blue light glow on the wall, no people",
   "காவல்துறை ரோந்து கைது"),
  ("A broken padlock hanging from a forced iron gate, close-up, daylight",
   "கொள்ளை திருட்டு உடைப்பு"),
  ("An open steel almirah with drawers pulled out and emptied in a dim room, no people",
   "கொள்ளை திருட்டு வீடு உடைப்பு"),
  ("A heavy bank strong-room door standing ajar in an empty corridor, no people",
   "வங்கி கொள்ளை பணம் திருட்டு"),
  ("A shattered glass display case with empty velvet trays in a small jewellery shop, no people",
   "நகை கொள்ளை திருட்டு கடை"),
  ("A CCTV camera fixed on the wall of a closed shop at night, street light glow",
   "கண்காணிப்பு கேமரா திருட்டு ஆதாரம்"),
  ("An overturned metal cash box and scattered empty boxes on a shop floor, no people",
   "கொள்ளை பணம் திருட்டு"),
  ("A single broken glass bangle lying on a dusty roadside, close-up, sombre light",
   "பாலியல் வன்கொடுமை பெண் தாக்குதல்"),
  ("An empty women's helpline desk with a telephone and a closed register in a plain room",
   "பெண்கள் புகார் உதவி எண் பாதுகாப்பு"),
  ("A deserted school corridor at dusk with long shadows, completely empty",
   "சிறுமி மாணவி பாதுகாப்பு குற்றம்"),
  ("Reception counter of an all-women police station, empty, daylight through a window",
   "மகளிர் காவல் நிலையம் புகார் வழக்கு"),
  ("A lone bus stop shelter on an empty road at night under a single street lamp",
   "பெண் பாதுகாப்பு இரவு தாக்குதல்"),
  ("A child's small school bag left alone on an empty stone bench, soft evening light",
   "குழந்தை சிறுமி பாதுகாப்பு குற்றம்"),
  ("Empty police station reception desk with a thick duty register and an old black telephone",
   "காவல் நிலையம் புகார் வழக்கு"),
  ("A pair of steel handcuffs resting on a scratched wooden table, dim light",
   "கைது குற்றவாளி காவல்"),
  ("A khaki police cap resting on a desk beside a closed brown file, close-up",
   "காவல்துறை போலீஸ் விசாரணை"),
  ("Locked iron bars of a lock-up corridor under harsh overhead light, no people",
   "சிறை கைது காவல் தடுப்பு"),
  ("A police patrol jeep on an empty highway at dawn, wide shot, no people",
   "காவல்துறை ரோந்து சோதனை"),
  ("Seized bottles, sealed packets and plain evidence bags arranged in rows on a table for a police display, no people",
   "பறிமுதல் கஞ்சா மது கடத்தல் சோதனை"),
 ],

 # ── பொருளாதாரம் ──────────────────────────────────────────────────────
 "economy": [
  ("Stacks of Indian coins and a small brass weighing balance on a dark wooden surface, close-up, no currency notes, no portraits",
   "பணம் ரூபாய் நிதி வருமானம்"),
  ("Gold bangles, chains and coins arranged in a jeweller's display tray, warm light, no people",
   "தங்கம் நகை விலை பவுன்"),
  ("Stacked silver bars on a dark surface under studio light",
   "வெள்ளி விலை உலோகம்"),
  ("A glowing digital stock market ticker board with out-of-focus coloured numbers, no readable text",
   "பங்குச்சந்தை சென்செக்ஸ் நிஃப்டி முதலீடு"),
  ("A vegetable market stall in Tamil Nadu with baskets of tomatoes, onions and greens, no people",
   "விலை சந்தை காய்கறி பொருள்"),
  ("An open wooden cash drawer of a small shop with compartments of coins and a bill spike, close-up, deserted counter, no currency notes",
   "வியாபாரம் கடை பணம் விற்பனை"),
  ("An empty bank counter with a token dispenser and a closed ledger, no people",
   "வங்கி கடன் வட்டி சேமிப்பு"),
  ("Jute grain sacks stacked high in a wholesale market warehouse, no people",
   "நெல் அரிசி சந்தை விலை கொள்முதல்"),
  ("A calculator, a ruled ledger and a pen on a trader's wooden desk, morning light",
   "கணக்கு வரி பட்சி நிதி"),
  ("A petrol pump nozzle resting in a fuel dispenser, close-up, no readable display",
   "பெட்ரோல் டீசல் எரிபொருள் விலை"),
 ],

 # ── சுகாதாரம் ────────────────────────────────────────────────────────
 "health": [
  ("Long empty corridor of a South Indian government hospital, daylight, no people",
   "மருத்துவமனை சிகிச்சை நோயாளி"),
  ("A stethoscope resting on a closed medical file on a wooden desk, close-up",
   "மருத்துவர் பரிசோதனை சிகிச்சை"),
  ("Blister packs of tablets and capsules beside a glass of water on a table, close-up",
   "மருந்து மாத்திரை சிகிச்சை"),
  ("A vaccine vial, a sealed syringe and cotton swabs laid out on a stainless steel tray, close-up, deserted clinic table",
   "தடுப்பூசி ஊசி சிகிச்சை"),
  ("An ambulance parked at a hospital entrance in the evening, no people",
   "ஆம்புலன்ஸ் அவசர சிகிச்சை"),
  ("Rows of medicine bottles and boxes on a pharmacy shelf, no readable labels",
   "மருந்தகம் மருந்து விலை"),
  ("A blood pressure cuff and its round gauge coiled on an empty clinic table beside a stethoscope, close-up, no person",
   "இரத்த அழுத்தம் பரிசோதனை இதயம்"),
  ("A small rural primary health centre building with a tiled roof and a compound wall, no people",
   "ஆரம்ப சுகாதார நிலையம் கிராமம்"),
  ("Fresh greens, millets and vegetables arranged on a banana leaf, overhead shot",
   "ஊட்டச்சத்து உணவு ஆரோக்கியம்"),
  ("An empty hospital bed with clean white sheets beside a sunlit window",
   "மருத்துவமனை படுக்கை சிகிச்சை"),
 ],

 # ── வேலைவாய்ப்பு ─────────────────────────────────────────────────────
 "jobs": [
  ("An empty examination hall with wooden desks arranged in neat rows, daylight, no people",
   "தேர்வு போட்டித்தேர்வு எழுத்துத்தேர்வு"),
  ("A wooden noticeboard with blank white sheets pinned in rows, outdoor light",
   "அறிவிப்பு அறிக்கை விண்ணப்பம்"),
  ("An office desk with a laptop, a resume folder and a pen, morning light, no people",
   "விண்ணப்பம் நேர்காணல் பணி"),
  ("A factory assembly line in Tamil Nadu with machinery and conveyor belts, no people",
   "தொழிற்சாலை உற்பத்தி பணி வேலை"),
  ("An interview table with two empty chairs facing each other in a plain room",
   "நேர்காணல் தேர்வு பணி நியமனம்"),
  ("A blank printed application form, a pen and a paper clip on a wooden desk, close-up, deserted, no writing on the form",
   "விண்ணப்பம் படிவம் பதிவு"),
  ("An IT office interior with rows of empty workstations and monitors, no people",
   "தகவல் தொழில்நுட்பம் அலுவலகம் வேலை"),
  ("A government employment exchange counter with queue rails, empty, daylight",
   "வேலைவாய்ப்பு அலுவலகம் பதிவு"),
  ("A construction site with scaffolding and safety helmets resting on a beam, no people",
   "கட்டுமான தொழிலாளர் பணி"),
  ("An appointment order envelope, a pen and spectacles on a plain desk, close-up",
   "நியமன ஆணை பணி உத்தரவு"),
 ],

 # ── அரசு அறிவிப்புகள் ────────────────────────────────────────────────
 "govt": [
  ("Facade of a large South Indian government secretariat building with a bare flag pole, no people, no emblem",
   "அரசு செயலகம் அறிவிப்பு உத்தரவு"),
  ("An official file tied with red tape resting on a wooden government desk, close-up",
   "அரசாணை கோப்பு உத்தரவு"),
  ("An empty government office with grey steel almirahs and stacked registers, daylight",
   "அரசு அலுவலகம் ஆவணம் நிர்வாகம்"),
  ("A village panchayat office building with a tiled roof and a blank notice board, no people",
   "ஊராட்சி பஞ்சாயத்து கிராமம்"),
  ("A ration shop counter with sacks of rice and pulses stacked behind, no people",
   "ரேஷன் நியாயவிலை அரிசி"),
  ("A state transport bus depot with buses lined up in the early morning, no people",
   "போக்குவரத்து பேருந்து அரசு"),
  ("A plain unmarked rubber stamp pressed on an open document, close-up, no emblem, no writing",
   "உத்தரவு அனுமதி பதிவு ஆவணம்"),
  ("Steel queue rails outside a taluk office entrance, empty, harsh noon light",
   "தாலுகா அலுவலகம் மனு விண்ணப்பம்"),
  ("A concrete overhead water tank and pipelines in a Tamil Nadu village, no people",
   "குடிநீர் திட்டம் கிராமம்"),
  ("A newly built concrete community hall with a bare flag pole in a village, no people",
   "அரசு திட்டம் கட்டிடம் திறப்பு"),
 ],

 # ── தொழில்நுட்பம் ───────────────────────────────────────────────────
 "tech": [
  ("A smartphone with a blank dark screen lying face up on a wooden table beside a charging cable, close-up, no person",
   "செல்போன் ஸ்மார்ட்போன் செயலி"),
  ("A tall mobile telephone tower against a clear blue sky",
   "கைபேசி கோபுரம் நெட்வொர்க் இணைப்பு"),
  ("Fibre optic cables plugged into a network switch, close-up, indicator lights",
   "இணையம் ஃபைபர் இணைப்பு"),
  ("A printed QR code board propped on an empty small shop counter beside a coin tray, no person, no text",
   "டிஜிட்டல் பணம் யுபிஐ கட்டணம்"),
  ("A server room with tall racks and rows of blinking indicator lights, no people",
   "தரவு சேவையகம் கணினி"),
  ("A laptop keyboard close-up in low light with a soft glow",
   "கணினி மென்பொருள் தொழில்நுட்பம்"),
  ("A large satellite dish antenna against a blue sky",
   "செயற்கைக்கோள் ஒளிபரப்பு தொடர்பு"),
  ("Macro shot of a circuit board with chips and coloured components",
   "சிப் மின்னணு உற்பத்தி"),
  ("An electric two-wheeler plugged in at a charging point on a street, no people",
   "மின்சார வாகனம் சார்ஜிங்"),
  ("A small drone flying low over green paddy fields, wide shot",
   "ட்ரோன் தொழில்நுட்பம் வேளாண்மை"),
 ],

 # ── இந்தியா ─────────────────────────────────────────────────────────
 "india": [
  ("A grand circular parliament-style government building exterior, wide shot, clear sky, no people, no emblem",
   "நாடாளுமன்றம் மத்திய அரசு மசோதா"),
  ("The Indian national tricolour flag fluttering against a blue sky, low angle",
   "இந்தியா தேசியம் கொடி"),
  ("A long-distance express train crossing a rural landscape at golden hour",
   "ரயில் பயணம் இந்தியா"),
  ("A multi-lane national highway with vehicles at dusk, motion blur, no people",
   "நெடுஞ்சாலை போக்குவரத்து இந்தியா"),
  ("An aerial view of a dense Indian city skyline with rooftops at dawn",
   "நகரம் இந்தியா வளர்ச்சி"),
  ("An Indian railway platform with iron pillars, benches and luggage trolleys, completely deserted at dawn",
   "ரயில் நிலையம் பயணம்"),
  ("A closed dark blue passport lying on a wooden table beside spectacles and a ticket folder, close-up, no text, no portrait, deserted",
   "குடியுரிமை கடவுச்சீட்டு இந்தியா"),
  ("An Indian Air Force transport aircraft on a runway under a wide sky, no people",
   "ராணுவம் பாதுகாப்பு மத்திய அரசு"),
  ("A long river bridge with concrete pillars, wide landscape, evening light",
   "பாலம் ஆறு திட்டம் இந்தியா"),
  ("A vast solar panel farm stretching to the horizon under bright sun",
   "சூரிய மின்சக்தி திட்டம்"),
 ],

 # ── உலகம் ───────────────────────────────────────────────────────────
 "world": [
  ("Flags of many nations on poles against a grey overcast sky, no readable markings",
   "உலகம் நாடுகள் உச்சிமாநாடு"),
  ("An empty international conference hall with curved rows of desks and microphones",
   "மாநாடு பேச்சுவார்த்தை ஒப்பந்தம்"),
  ("A world globe on a wooden desk beside a closed notebook, warm light",
   "உலகம் வெளியுறவு நாடு"),
  ("A huge container ship docked at a port, aerial view, no people",
   "வர்த்தகம் ஏற்றுமதி துறைமுகம்"),
  ("An airport runway with a passenger aircraft taking off at dawn",
   "விமானம் பயணம் சர்வதேசம்"),
  ("A foreign metropolis skyline with glass towers at dusk, wide shot",
   "நகரம் உலகம் பொருளாதாரம்"),
  ("An empty circular assembly chamber with tiered seating and desks",
   "ஐக்கிய நாடுகள் அவை தீர்மானம்"),
  ("A passport and a boarding pass lying on a table, close-up, no readable text",
   "விசா பயணம் குடியேற்றம்"),
  ("Blank currency exchange counter boards in an airport hall, no people",
   "நாணயம் மாற்று விகிதம் டாலர்"),
  ("A glacier front meeting dark sea water under a pale sky, wide shot",
   "காலநிலை மாற்றம் உலகம் வெப்பம்"),
 ],

 # ── விளையாட்டு ──────────────────────────────────────────────────────
 "sports": [
  ("An empty cricket stadium with floodlights glowing at dusk, wide shot",
   "கிரிக்கெட் போட்டி அணி ஆட்டம்"),
  ("A plain cricket bat, a red ball and three stumps arranged on green turf, close-up, no logos, no text, deserted ground",
   "கிரிக்கெட் பேட் விக்கெட் ரன்"),
  ("A mud kabaddi court marked with white lines, dust in the air, no players",
   "கபடி போட்டி ஆட்டம்"),
  ("Silambam sticks and a traditional practice ground at sunrise, no people",
   "சிலம்பம் பாரம்பரிய விளையாட்டு"),
  ("Empty athletics running track lanes seen from directly above",
   "தடகளம் ஓட்டம் போட்டி"),
  ("A jallikattu arena barricade with dust hanging in the air, no animals, no people",
   "ஜல்லிக்கட்டு பாரம்பரியம் போட்டி"),
  ("Gold, silver and bronze medals hanging on a wooden stand, close-up",
   "பதக்கம் தங்கம் வெள்ளி வெற்றி"),
  ("A football resting on a wet grass field, close-up, floodlight glow",
   "கால்பந்து போட்டி அணி"),
  ("Hockey sticks and a ball lying on a blue turf field",
   "ஹாக்கி போட்டி அணி"),
  ("Empty swimming pool lanes with clear blue water and lane ropes",
   "நீச்சல் போட்டி வீரர்"),
 ],

 # ── சினிமா ──────────────────────────────────────────────────────────
 "cinema": [
  ("A professional film camera on a tripod on a shooting set with lights behind, no people",
   "படப்பிடிப்பு திரைப்படம் இயக்குநர்"),
  ("An empty cinema hall with red seats and a blank white screen",
   "திரையரங்கம் வெளியீடு ரிலீஸ்"),
  ("A blank clapperboard resting on a film set floor, no writing on it",
   "படப்பிடிப்பு பூஜை துவக்கம்"),
  ("Studio lights and silver reflectors arranged on a shooting floor, no people",
   "படப்பிடிப்பு ஸ்டூடியோ"),
  ("Rolls of film reel and a metal canister on a wooden table, close-up",
   "திரைப்படம் பழைய சினிமா"),
  ("A studio recording microphone with a pop filter in a sound booth, no people",
   "ஆடியோ பாடல் இசை வெளியீடு"),
  ("An empty director's chair on a film set at golden hour",
   "இயக்குநர் படப்பிடிப்பு"),
  ("A dark movie projection room with a film projector running, no people",
   "திரையிடல் திரையரங்கம்"),
  ("An empty red carpet with rope barricades at an event entrance, evening lights",
   "விழா வெளியீடு பிரபலம்"),
  ("A mixing console with faders and knobs in a music studio, close-up, no people",
   "இசை பாடல் ஆல்பம் வெளியீடு"),
 ],

 # ── கல்வி ───────────────────────────────────────────────────────────
 "edu": [
  ("An empty classroom with old wooden benches and a blank blackboard, daylight",
   "பள்ளி வகுப்பு மாணவர் கல்வி"),
  ("A government school building with a tiled roof and a bare compound, no people",
   "அரசு பள்ளி கல்வி கட்டிடம்"),
  ("Tall library shelves packed with books, an aisle receding into light, no people",
   "நூலகம் புத்தகம் கல்வி"),
  ("A yellow school bus parked in an empty ground, morning light",
   "பள்ளி பேருந்து மாணவர்"),
  ("Rows of desks in a large examination hall with answer sheets placed ready, no people",
   "தேர்வு பொதுத்தேர்வு மாணவர் மதிப்பெண்"),
  ("A college corridor with arches and pillars, sunlight on the floor, empty",
   "கல்லூரி மாணவர் உயர்கல்வி"),
  ("A school science laboratory bench with glass beakers, burner and specimens, no people",
   "அறிவியல் ஆய்வகம் கல்வி"),
  ("An empty school playground with a swing and a bare flag pole at dusk",
   "பள்ளி விளையாட்டு மைதானம்"),
  ("A stack of notebooks, a pen and a wooden ruler on a school desk, close-up",
   "பாடம் புத்தகம் மாணவர் கல்வி"),
  ("A bicycle parked against a school compound wall in the morning, no people",
   "மாணவி சைக்கிள் பள்ளி திட்டம்"),
 ],

 # ── வேளாண்மை ────────────────────────────────────────────────────────
 "agri": [
  ("Lush green paddy fields stretching to the horizon under a cloudy sky, no people",
   "நெல் விவசாயம் சாகுபடி பயிர்"),
  ("A woven bamboo winnowing tray heaped with freshly harvested golden paddy grains resting on the ground, close-up, deserted",
   "விவசாயி நெல் அறுவடை"),
  ("A tractor with a plough attachment parked at the edge of a freshly ploughed wet field, wide shot, deserted, no driver",
   "உழவு டிராக்டர் விவசாயம்"),
  ("An irrigation canal carrying water beside green fields, wide shot",
   "பாசனம் நீர் கால்வாய் அணை"),
  ("A coconut grove with tall palms and dappled sunlight, no people",
   "தென்னை தோப்பு விவசாயம்"),
  ("A dense sugarcane field with tall stalks at golden hour",
   "கரும்பு சாகுபடி விலை"),
  ("A wooden bullock cart standing in a village field at sunset, no people or animals in focus",
   "கிராமம் விவசாயம் பாரம்பரியம்"),
  ("Harvested grain spread out to dry on a village threshing floor, no people",
   "அறுவடை கொள்முதல் நெல் தானியம்"),
  ("Trays of vegetable seedlings in a nursery under shade net, close-up",
   "நாற்று விதை இயற்கை வேளாண்மை"),
  ("Cattle standing in a clean village shed with fodder, no people",
   "கால்நடை பால் பண்ணை"),
 ],

 # ── வானிலை / பேரிடர் ────────────────────────────────────────────────
 "weather": [
  ("Heavy monsoon rain falling on a flooded city street, no people, grey light",
   "மழை வெள்ளம் நீர் தேக்கம்"),
  ("Huge storm waves crashing on a rocky coastline under dark clouds",
   "புயல் கடல் எச்சரிக்கை"),
  ("A dry cracked lake bed under a harsh white sky, wide shot",
   "வறட்சி நீர் பஞ்சம் ஏரி"),
  ("Rain drops running down a window pane with an empty deserted street blurred beyond, grey light",
   "மழை வானிலை பருவமழை"),
  ("A large uprooted tree lying across an empty road after a storm",
   "புயல் சேதம் மரம் விழுந்தது"),
  ("Dark rain clouds gathering over green paddy fields, wide landscape",
   "மழை வானிலை முன்னறிவிப்பு"),
  ("Rows of empty mats and folded blankets inside a relief camp hall, no people",
   "நிவாரணம் முகாம் பாதிப்பு"),
  ("A waterlogged bus stand with a bus standing in knee-deep water, no people",
   "வெள்ளம் நீர் தேக்கம் போக்குவரத்து"),
 ],

 # ── போக்குவரத்து ───────────────────────────────────────────────────
 "transport": [
  ("A row of state transport buses lined up in a depot at dawn, no people",
   "பேருந்து போக்குவரத்து கட்டணம்"),
  ("An empty railway platform at dawn with a train standing, no people",
   "ரயில் நிலையம் பயணம்"),
  ("A metro train standing at a modern underground platform, no people",
   "மெட்ரோ ரயில் நகரம்"),
  ("A highway toll plaza with lanes and barriers, seen from the front, no people",
   "சுங்கச்சாவடி நெடுஞ்சாலை கட்டணம்"),
  ("A row of yellow auto rickshaws parked along a street, no people",
   "ஆட்டோ கட்டணம் போக்குவரத்து"),
  ("A traffic signal glowing red at a city junction at dusk, light trails",
   "போக்குவரத்து சிக்னல் நெரிசல்"),
  ("An aircraft parked at an airport apron with ground equipment, no people",
   "விமானம் விமான நிலையம் பயணம்"),
  ("Goods lorries moving on a national highway at dusk, motion blur",
   "சரக்கு லாரி போக்குவரத்து"),
 ],

 # ── மின்சாரம் / குடிநீர் ────────────────────────────────────────────
 "power": [
  ("A street-side electric transformer with cables and insulators, close-up",
   "மின்சாரம் மின்மாற்றி தடை"),
  ("High tension electricity towers marching across open land at sunset",
   "மின் இணைப்பு மின்சாரம் திட்டம்"),
  ("A concrete overhead water tank standing above a village at noon, no people",
   "குடிநீர் தண்ணீர் திட்டம்"),
  ("A long row of empty coloured plastic pots waiting in a queue on a street, no people",
   "தண்ணீர் பற்றாக்குறை குடிநீர்"),
  ("A dam spillway with water gushing out through open shutters, wide shot",
   "அணை நீர் திறப்பு பாசனம்"),
  ("Rooftop solar panels on a row of houses under bright sun",
   "சூரிய மின்சக்தி மானியம்"),
  ("Wind turbines standing over dry Tamil Nadu farmland at golden hour",
   "காற்றாலை மின் உற்பத்தி"),
  ("Tall chimneys of a thermal power station against a hazy sky",
   "அனல் மின் நிலையம் உற்பத்தி"),
 ],

 # ── உள்ளாட்சி ───────────────────────────────────────────────────────
 "local": [
  ("A small village panchayat office with a tiled roof and a blank notice board, no people",
   "ஊராட்சி பஞ்சாயத்து கிராமம்"),
  ("A town municipal office building with an arched entrance, no people",
   "நகராட்சி மாநகராட்சி நிர்வாகம்"),
  ("Green and blue waste segregation bins on a clean street corner",
   "குப்பை தூய்மை நகராட்சி"),
  ("A road being laid with fresh tar and a roller standing idle, no people",
   "சாலை பணி தார் அமைப்பு"),
  ("A row of new LED street lights on poles along a village road at dusk",
   "தெரு விளக்கு ஊராட்சி வசதி"),
  ("An open storm water drain under construction along a street, no people",
   "கழிவுநீர் வடிகால் பணி"),
  ("A small rural bus stand shelter with concrete benches, empty",
   "பேருந்து நிறுத்தம் கிராமம்"),
  ("A village pond with steps and surrounding coconut trees, calm water",
   "குளம் ஏரி தூர்வாரல் ஊராட்சி"),
 ],

 # ── அரசியல் நிகழ்வு ─────────────────────────────────────────────────
 "politics": [
  ("An empty public meeting ground with rows of plastic chairs facing a bare stage at dusk",
   "பொதுக்கூட்டம் மாநாடு அரசியல்"),
  ("Plain coloured flags without any symbol or text fluttering on bamboo poles along a road",
   "கட்சி கொடி பிரச்சாரம்"),
  ("A sealed ballot box and a wooden voting compartment in an empty polling room",
   "தேர்தல் வாக்குப்பதிவு வாக்காளர்"),
  ("An empty press conference table with several plain microphones and chairs, no logos",
   "செய்தியாளர் சந்திப்பு அறிக்கை"),
  ("Interior of an empty legislative assembly style chamber with curved desks, no emblem",
   "சட்டப்பேரவை கூட்டத்தொடர் மசோதா"),
  ("A city road lined with steel barricades ahead of a procession, no people",
   "பேரணி ஊர்வலம் போராட்டம்"),
  ("A cluster of loudspeaker horns mounted on a tall pole against the sky",
   "பிரச்சாரம் அறிவிப்பு கூட்டம்"),
  ("A bare wooden dais with a plain lectern and a cluster of microphones on an empty open ground at dusk, deserted",
   "கூட்டம் பேரணி ஆதரவு"),
 ],

 # ── விபத்து ─────────────────────────────────────────────────────────
 "accident": [
  ("A badly damaged car resting on a roadside after a collision, no people",
   "விபத்து கார் சாலை உயிரிழப்பு"),
  ("An overturned goods lorry lying beside a highway, no people",
   "லாரி விபத்து நெடுஞ்சாலை"),
  ("An ambulance with flashing lights on a dark road at night, no people",
   "ஆம்புலன்ஸ் மீட்பு விபத்து"),
  ("A bus with a shattered windscreen parked at the roadside, no people",
   "பேருந்து விபத்து பயணிகள்"),
  ("Long black skid marks on a wet road at dawn, close-up",
   "விபத்து சாலை பாதுகாப்பு"),
  ("A closed railway level crossing gate with red and white stripes, no people",
   "ரயில்வே கேட் விபத்து"),
  ("A hospital emergency entrance with a ramp and trolley at night, no people",
   "அவசர சிகிச்சை மீட்பு"),
  ("Rubble and twisted steel rods of a collapsed building, daylight, no people",
   "கட்டிடம் இடிந்து விபத்து மீட்பு"),
 ],

 # ── மீனவர் / கடல் ───────────────────────────────────────────────────
 "fisher": [
  ("Wooden catamaran fishing boats drawn up on a Tamil Nadu beach at dawn, no people",
   "மீனவர் படகு கடல் தொழில்"),
  ("Fishing nets spread out to dry on a sandy shore, close-up",
   "வலை மீன்பிடி மீனவர்"),
  ("A fishing harbour crowded with moored trawlers, wide shot, no people",
   "துறைமுகம் படகு மீன்பிடி தடை"),
  ("Empty cane baskets and weighing scales at a fish market, no people, early light",
   "மீன் சந்தை விலை"),
  ("A white lighthouse standing on a rocky coast under a clear sky",
   "கடல் கலங்கரை எச்சரிக்கை"),
  ("Rough sea waves striking black coastal rocks, spray in the air",
   "கடல் சீற்றம் மீனவர் எச்சரிக்கை"),
  ("A coastal fishing village with thatched huts behind a row of boats, no people",
   "மீனவ கிராமம் கடலோரம்"),
  ("Coiled nylon ropes and floats piled on a boat deck, close-up",
   "படகு மீன்பிடி உபகரணம்"),
 ],

 # ── தொழிலாளர் ───────────────────────────────────────────────────────
 "labour": [
  ("A multi-storey building under construction with bamboo scaffolding, no people",
   "கட்டுமான தொழிலாளர் ஊதியம்"),
  ("Rows of spinning machines inside a textile mill, no people",
   "ஆலை நூற்பாலை தொழிலாளர்"),
  ("Stacked red bricks and tall chimneys at a brick kiln, no people",
   "செங்கல் சூளை தொழிலாளர்"),
  ("Neat rows of tea bushes on a misty hillside estate, no people",
   "தேயிலை தோட்டம் தொழிலாளர்"),
  ("Salt pans with white mounds of salt under a bright sky, no people",
   "உப்பளம் தொழிலாளர் உற்பத்தி"),
  ("An automotive assembly line with robotic arms and car frames, no people",
   "தொழிற்சாலை உற்பத்தி வேலை"),
  ("Worn tools, a helmet and gloves resting on a wooden plank at a work site",
   "தொழிலாளர் பணி பாதுகாப்பு"),
  ("Sacks being stacked on a lorry at a warehouse loading bay, no people",
   "சுமை தூக்கும் தொழிலாளர் கூலி"),
 ],

 # ── மகளிர் / குழந்தை ────────────────────────────────────────────────
 "women": [
  ("A small anganwadi centre building painted in bright colours with a play area, no people",
   "அங்கன்வாடி குழந்தை சத்துணவு"),
  ("An empty school playground with a slide and swings in the morning",
   "குழந்தை பள்ளி விளையாட்டு"),
  ("A community hall with plastic chairs arranged in a circle for a self-help group meeting, no people",
   "மகளிர் சுயஉதவிக்குழு கடன்"),
  ("A row of tailoring machines on a long table in a training centre, no people",
   "மகளிர் பயிற்சி தொழில் வேலைவாய்ப்பு"),
  ("Large steel vessels and serving ladles in a mid-day meal kitchen, no people",
   "சத்துணவு குழந்தை பள்ளி"),
  ("A row of children's bicycles parked beside a school wall, no people",
   "குழந்தை பள்ளி திட்டம்"),
  ("A wooden cradle with a soft cloth in a sunlit room, no people",
   "குழந்தை நலன் தாய் திட்டம்"),
  ("A women's working hostel building with balconies and a compound wall, no people",
   "மகளிர் விடுதி பாதுகாப்பு"),
 ],

 # ── ஓய்வூதியம் / மூத்த குடிமக்கள் ──────────────────────────────────
 "pension": [
  ("An old age home verandah with empty wooden chairs facing a garden, soft light",
   "முதியோர் இல்லம் ஓய்வூதியம்"),
  ("A walking stick and a pair of spectacles resting on a wooden table, close-up",
   "முதியோர் உதவித்தொகை நலன்"),
  ("A bank passbook and an official order paper on a desk, close-up, no readable text",
   "ஓய்வூதியம் வங்கி உதவித்தொகை"),
  ("A post office counter with a weighing scale and a closed register, no people",
   "தபால் நிலையம் உதவித்தொகை"),
  ("An empty wooden chair beside a window with warm afternoon sunlight",
   "முதியோர் ஓய்வு நலத்திட்டம்"),
  ("Steel queue rails outside a treasury office entrance, empty, daylight",
   "கருவூலம் ஓய்வூதியம் வழங்கல்"),
 ],

 # ── சுற்றுச்சூழல் ──────────────────────────────────────────────────
 "env": [
  ("Plastic bottles and waste scattered on a beach at low tide, no people",
   "பிளாஸ்டிக் கழிவு மாசு கடல்"),
  ("Thick smog hanging over a city skyline at sunrise",
   "காற்று மாசு சுற்றுச்சூழல்"),
  ("A dense mangrove forest with roots in shallow water, wide shot",
   "அலையாத்தி காடு பாதுகாப்பு"),
  ("A dried up lake with cracked earth and a lone dead tree",
   "ஏரி வறட்சி நீர்நிலை"),
  ("Hundreds of tree saplings in black nursery bags arranged in rows",
   "மரக்கன்று நடுதல் பசுமை"),
  ("A misty evergreen forest with tall trees and filtered sunlight",
   "வனம் காடு பாதுகாப்பு வனவிலங்கு"),
  ("A river carrying floating waste past a concrete bank, daylight",
   "ஆறு மாசு கழிவுநீர்"),
  ("A wild elephant standing at the edge of a misty forest clearing, wide shot, no people anywhere",
   "யானை வனவிலங்கு காடு"),
 ],

 # ── கோயில் / திருவிழா ──────────────────────────────────────────────
 "temple": [
  ("Silhouette of a tall South Indian temple gopuram against a dawn sky, wide shot",
   "கோயில் கோபுரம் ஆலயம்"),
  ("A stone temple tank with steps on all four sides, still water, no people",
   "கோயில் குளம் தீர்த்தம்"),
  ("Rows of lit brass oil lamps in a temple corridor at dusk, no people",
   "விளக்கு பூஜை வழிபாடு"),
  ("Close-up of a massive carved wooden temple chariot wheel",
   "தேர் திருவிழா ஊர்வலம்"),
  ("A festive meal served on a banana leaf, overhead shot, no people",
   "திருவிழா விருந்து படையல்"),
  ("An intricate white rice-flour kolam drawn on a red-bordered doorstep",
   "கோலம் பண்டிகை வீடு"),
  ("Strings of jasmine and rose garlands hanging at a flower stall, no people",
   "மலர் மாலை பூஜை"),
  ("A long pillared temple corridor with carved stone columns, sunlight and shadow, no people",
   "ஆலயம் மண்டபம் சிற்பம்"),
 ],

 # ── விண்வெளி / அறிவியல் ────────────────────────────────────────────
 "space": [
  ("A tall white rocket standing on a launch pad at dawn, wide shot, no people",
   "ராக்கெட் ஏவுதல் விண்வெளி"),
  ("An array of large white satellite dishes pointing at the sky",
   "செயற்கைக்கோள் கண்காணிப்பு"),
  ("A clear night sky full of stars over an open field, long exposure",
   "வானியல் விண்மீன் ஆய்வு"),
  ("An empty mission control room with rows of dark consoles and screens, no people, no text",
   "விண்வெளி ஆய்வு கட்டுப்பாட்டு மையம்"),
  ("A gold-foil covered satellite model with solar panels on a stand",
   "செயற்கைக்கோள் ஏவுதல் ஆய்வு"),
  ("A rocket contrail arcing across a clear blue sky after launch",
   "ராக்கெட் ஏவுதல் வெற்றி"),
  ("A white observatory dome on a hilltop under a starry sky",
   "வானியல் ஆய்வகம் தொலைநோக்கி"),
  ("The curved blue edge of Earth seen from orbit with black space beyond",
   "பூமி விண்வெளி ஆய்வு"),
 ],

 # ── பாதுகாப்பு / ராணுவம் ───────────────────────────────────────────
 "defence": [
  ("A grey naval warship sailing on open sea under a clear sky, no people",
   "கடற்படை போர்க்கப்பல் பாதுகாப்பு"),
  ("Three fighter jets flying in formation high against a blue sky",
   "விமானப்படை போர் விமானம்"),
  ("An army truck convoy on a winding mountain road, far distance, no people",
   "ராணுவம் எல்லை பாதுகாப்பு"),
  ("A tall border fence with watchtowers stretching across barren land at dusk, no people",
   "எல்லை பாதுகாப்பு ஊடுருவல்"),
  ("Combat boots and a helmet placed neatly on a wooden bench, close-up",
   "வீரர் ராணுவம் தியாகம்"),
  ("A large white radar dome on a hillside against an evening sky",
   "கண்காணிப்பு ராடார் பாதுகாப்பு"),
  ("A submarine moored at a naval harbour, wide shot, no people",
   "நீர்மூழ்கி கடற்படை"),
  ("A military helicopter flying low over a coastline, no people visible",
   "ஹெலிகாப்டர் மீட்பு ராணுவம்"),
 ],
}



GALLERY_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f6f4ef;color:#1a1a1a;
     font-family:"Noto Sans Tamil","Latha",system-ui,sans-serif}
header{background:#7a1f1f;color:#fff;padding:18px 20px;position:sticky;top:0;z-index:5}
header h1{margin:0;font-size:20px;font-weight:700}
header p{margin:4px 0 0;font-size:13px;opacity:.85}
nav{padding:12px 20px;background:#fff;border-bottom:1px solid #e3ded4;
    display:flex;flex-wrap:wrap;gap:6px}
nav a{font-size:13px;text-decoration:none;color:#7a1f1f;border:1px solid #d9cfc0;
      border-radius:14px;padding:3px 10px;background:#fdfbf7}
main{padding:20px;max-width:1500px;margin:0 auto}
h2{font-size:17px;margin:30px 0 12px;padding-bottom:6px;border-bottom:2px solid #7a1f1f}
h2 span{font-weight:400;font-size:13px;color:#6b6257;margin-left:8px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
figure{margin:0;background:#fff;border:1px solid #e3ded4;border-radius:8px;overflow:hidden}
figure img{width:100%;display:block;aspect-ratio:1/1;object-fit:cover;background:#eee}
figcaption{padding:7px 9px;font-size:12px;line-height:1.45}
.fn{color:#8a8178;font-size:11px;font-family:ui-monospace,monospace}
.tg{color:#1a1a1a;margin-top:2px}
footer{padding:26px 20px;text-align:center;color:#8a8178;font-size:12px}
"""


def write_gallery(idx):
    """படக் களஞ்சியத்தைப் பார்வையிட ஒரு HTML பக்கம் (செலவு இல்லை)."""
    import html as _h
    order = [k for k in BANK if k in idx] + [k for k in idx if k not in BANK]
    total = sum(len(idx[k]) for k in order)
    nav = "".join(f'<a href="#{k}">{TOPIC_TA.get(k, k)}</a>' for k in order)
    body = []
    for k in order:
        rows = sorted(idx[k], key=lambda r: r.get("file", ""))
        cards = []
        for r in rows:
            fn = r.get("file", "").split("/")[-1]
            cards.append(
                '<figure><img loading="lazy" src="{f}" alt="">'
                '<figcaption><div class="fn">{n}</div>'
                '<div class="tg">{t}</div></figcaption></figure>'.format(
                    f=_h.escape(fn), n=_h.escape(fn),
                    t=_h.escape(r.get("tags", ""))))
        body.append(
            '<h2 id="{k}">{ta} <span>{k} · {c} படம்</span></h2>'
            '<div class="grid">{cards}</div>'.format(
                k=k, ta=_h.escape(TOPIC_TA.get(k, k)), c=len(rows),
                cards="".join(cards)))
    page = (
        '<!doctype html><html lang="ta"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<title>படக் களஞ்சியம் — துலாமுள்</title>'
        '<style>' + GALLERY_CSS + '</style></head><body>'
        '<header><h1>படக் களஞ்சியம்</h1>'
        '<p>' + str(len(order)) + ' துறை · ' + str(total) + ' படம் · '
        'உள் பயன்பாட்டிற்கு மட்டும்</p></header>'
        '<nav>' + nav + '</nav><main>' + "".join(body) + '</main>'
        '<footer>முத்தமிழ் கலைக்கூடம் · துலாமுள்</footer></body></html>')
    (OUT / "index.html").write_text(page, encoding="utf-8")
    print(f"காட்சியகம்: data/bank/index.html ({len(order)} துறை, {total} படம்)")

def gen(prompt, topic="", tries=2):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY இல்லை")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "gemini-2.5-flash-image:generateContent")
    body = STYLE + STYLE_EXTRA.get(topic, "") + "\n\nSCENE: " + prompt
    for attempt in range(tries):
        try:
            resp = requests.post(
                url,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": body}]}],
                      "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}},
                timeout=120)
        except Exception as ex:
            print("   இணைப்பு பிழை:", str(ex)[:140]); time.sleep(5); continue
        try:
            r = resp.json()
        except Exception:
            print(f"   HTTP {resp.status_code} — JSON அல்ல:", resp.text[:160])
            time.sleep(5); continue

        if "candidates" not in r:
            err = r.get("error") or {}
            print(f"   API பிழை · HTTP {resp.status_code} · {err.get('status','')} "
                  f"· {str(err.get('message',''))[:200]}")
            if r.get("promptFeedback"):
                print("   promptFeedback:",
                      json.dumps(r["promptFeedback"], ensure_ascii=False)[:220])
            if not err and not r.get("promptFeedback"):
                print("   முழு பதில்:", json.dumps(r, ensure_ascii=False)[:300])
            time.sleep(5); continue

        cand = (r["candidates"] or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        for p in parts:
            if "inlineData" in p and p["inlineData"].get("data"):
                return base64.b64decode(p["inlineData"]["data"])
            d = p.get("inline_data")
            if d and d.get("data"):
                return base64.b64decode(d["data"])
        print("   படம் வரவில்லை · finishReason:", cand.get("finishReason"))
        said = [p.get("text", "") for p in parts if p.get("text")]
        if said:
            print("   மாதிரி சொன்னது:", said[0][:200])
        if cand.get("safetyRatings"):
            print("   safety:", json.dumps(cand["safetyRatings"], ensure_ascii=False)[:220])
        time.sleep(5)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--per", type=int, default=99)   # ஒரு துறைக்கு அதிகபட்சம்
    ap.add_argument("--redo", nargs="*", default=None,
                    help="மீண்டும் உருவாக்க வேண்டிய கோப்புகள், எ.கா. court04 crime13")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    idx = json.loads(IDX.read_text(encoding="utf-8")) if IDX.exists() else {}
    redo = set(a.redo or [])
    topics = a.only or list(BANK)
    made = 0
    for t in topics:
        items = BANK.get(t, [])
        if not items:
            print(f"[{t}] — அப்படி ஒரு துறை இல்லை"); continue
        idx.setdefault(t, [])
        for n, item in enumerate(items[: a.per], 1):
            prompt, tags = (item if isinstance(item, (list, tuple)) else (item, ""))
            stem = f"{t}{n:02d}"
            fp = OUT / f"{stem}.jpg"
            rec = {"file": f"data/bank/{stem}.jpg", "prompt": prompt, "tags": tags}
            if fp.exists() and stem not in redo:
                # படம் ஏற்கனவே இருக்கிறது — செலவே இல்லாமல் குறிச்சொற்களை மட்டும் புதுப்பி
                idx[t] = [r for r in idx[t] if r.get("file") != rec["file"]]
                idx[t].append(rec)
                continue
            print(f"[{t}] {n}/{len(items[: a.per])} — {prompt[:52]}…")
            b = gen(prompt, t)
            if not b:
                continue
            im = Image.open(io.BytesIO(b)).convert("RGB")
            im = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
            im.save(fp, "JPEG", quality=84, optimize=True)
            idx[t] = [r for r in idx[t] if r.get("file") != rec["file"]]
            idx[t].append(rec)
            made += 1
            time.sleep(2)
        idx[t].sort(key=lambda r: r.get("file", ""))
        IDX.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    write_gallery(idx)
    print(f"\nமுடிந்தது — {made} புதிய படம். மொத்தம்: " +
          ", ".join(f"{k}:{len(v)}" for k, v in sorted(idx.items())))


if __name__ == "__main__":
    main()
