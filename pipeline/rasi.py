"""
துலாமுள் — தினசரி பஞ்சாங்கம் + 12 ராசி பலன் (கணிதம்: Swiss Ephemeris, லாஹிரி; பலன்: rasi_rules.json விதிகள்)
Claude தேவையில்லை — முழுவதும் விதிப்படி; விதிகள் data/rasi_rules.json-ல் (ஆசிரியர் திருத்தலாம்).
"""
import json, random, datetime as dt
from pathlib import Path
import swisseph as swe

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "pipeline" / "rasi_rules.json"
swe.set_sid_mode(swe.SIDM_LAHIRI)

RASI = ['மேஷம்','ரிஷபம்','மிதுனம்','கடகம்','சிம்மம்','கன்னி','துலாம்','விருச்சிகம்','தனுசு','மகரம்','கும்பம்','மீனம்']
NAK = ['அஸ்வினி','பரணி','கிருத்திகை','ரோகிணி','மிருகசீரிஷம்','திருவாதிரை','புனர்பூசம்','பூசம்','ஆயில்யம்','மகம்','பூரம்','உத்திரம்',
       'ஹஸ்தம்','சித்திரை','சுவாதி','விசாகம்','அனுஷம்','கேட்டை','மூலம்','பூராடம்','உத்திராடம்','திருவோணம்','அவிட்டம்','சதயம்','பூரட்டாதி','உத்திரட்டாதி','ரேவதி']
TITHI = ['பிரதமை','துவிதியை','திருதியை','சதுர்த்தி','பஞ்சமி','சஷ்டி','சப்தமி','அஷ்டமி','நவமி','தசமி','ஏகாதசி','துவாதசி','திரயோதசி','சதுர்த்தசி']
VAARAM = ['திங்கள்','செவ்வாய்','புதன்','வியாழன்','வெள்ளி','சனி','ஞாயிறு']   # python weekday()
# ராகு காலம் / எமகண்டம் / குளிகை — வாரப்படி (சூரிய உதயம் 6:00 அடிப்படை)
RAHU  = {6:'4:30–6:00 மாலை',0:'7:30–9:00',1:'3:00–4:30',2:'12:00–1:30',3:'1:30–3:00',4:'10:30–12:00',5:'9:00–10:30'}
YAMA  = {6:'12:00–1:30',0:'10:30–12:00',1:'9:00–10:30',2:'7:30–9:00',3:'6:00–7:30',4:'3:00–4:30',5:'1:30–3:00'}
KULI  = {6:'3:00–4:30',0:'1:30–3:00',1:'12:00–1:30',2:'10:30–12:00',3:'9:00–10:30',4:'7:30–9:00',5:'6:00–7:30'}
NALLA = {6:'காலை 7:30–8:30, மாலை 4:30–5:30',0:'காலை 10:30–11:30, மாலை 4:30–5:30',1:'காலை 9:00–10:00, மாலை 3:00–4:00',
         2:'காலை 9:00–10:00, மாலை 3:00–4:00',3:'காலை 10:30–11:30, மாலை 4:30–5:30',4:'காலை 7:30–8:30, மாலை 3:00–4:00',5:'காலை 9:00–10:00, மாலை 3:00–4:00'}
# ராசிக்குரிய நட்சத்திரங்கள் (குறியீடு: நட்சத்திர எண்)
RASI_NAK = [[0,1,2],[2,3,4],[4,5,6],[6,7,8],[9,10,11],[11,12,13],[13,14,15],[15,16,17],[18,19,20],[20,21,22],[22,23,24],[24,25,26]]
TARA = ['ஜென்மம்','சம்பத்','விபத்','க்ஷேமம்','பிரத்யக்','சாதனை','நைதனம்','மித்ரம்','பரம மித்ரம்']
TARA_GOOD = {1,3,5,7,8}   # index: சம்பத், க்ஷேமம், சாதனை, மித்ரம், பரம மித்ரம்

def positions(date_ist):
    d = dt.datetime(date_ist.year, date_ist.month, date_ist.day, 6, 0) - dt.timedelta(hours=5, minutes=30)   # சூரிய உதயம் ≈ 6:00 IST
    jd = swe.julday(d.year, d.month, d.day, d.hour + d.minute / 60)
    P = {}
    for name, pid in [('sun', swe.SUN), ('moon', swe.MOON), ('mercury', swe.MERCURY), ('venus', swe.VENUS),
                      ('mars', swe.MARS), ('jupiter', swe.JUPITER), ('saturn', swe.SATURN), ('rahu', swe.MEAN_NODE)]:
        lon = swe.calc_ut(jd, pid, swe.FLG_SIDEREAL)[0][0] % 360
        P[name] = {'lon': lon, 'sign': int(lon // 30), 'nak': int(lon // (360 / 27))}
    P['ketu'] = {'lon': (P['rahu']['lon'] + 180) % 360, 'sign': int(((P['rahu']['lon'] + 180) % 360) // 30)}
    return P

def panchangam(date_ist, P):
    wd = date_ist.weekday()
    t = int(((P['moon']['lon'] - P['sun']['lon']) % 360) // 12) + 1
    paksha = 'சுக்ல பக்ஷம்' if t <= 15 else 'கிருஷ்ண பக்ஷம்'
    tithi = 'பௌர்ணமி' if t == 15 else 'அமாவாசை' if t == 30 else TITHI[(t - 1) % 15]
    return {'vaaram': VAARAM[wd], 'tithi': f'{tithi} · {paksha}', 'nakshatram': NAK[P['moon']['nak']],
            'chandra_rasi': RASI[P['moon']['sign']], 'rahu': RAHU[wd], 'yama': YAMA[wd], 'kuligai': KULI[wd], 'nalla': NALLA[wd],
            'gocharam': {k: RASI[P[k]['sign']] for k in ['sun', 'mercury', 'venus', 'mars', 'jupiter', 'saturn', 'rahu', 'ketu']}}

def palan(date_ist, P, rules, seed=None):
    rnd = random.Random(seed or date_ist.toordinal())
    wd = date_ist.weekday(); moon_sign = P['moon']['sign']; today_nak = P['moon']['nak']
    out = []
    for r in range(12):
        house = (moon_sign - r) % 12 + 1                      # சந்திரன் இந்த ராசிக்கு எத்தனையாம் இடம்
        taras = [((today_nak - n) % 27) % 9 for n in RASI_NAK[r]]
        good_t = sum(1 for x in taras if x in TARA_GOOD)
        tara_main = max(set(taras), key=taras.count)
        # கோசாரம்: குரு, சனி இந்த ராசிக்கு எத்தனையாம் இடம்
        guru_h = (P['jupiter']['sign'] - r) % 12 + 1; sani_h = (P['saturn']['sign'] - r) % 12 + 1
        score = rules['house_score'][str(house)] + (12 if good_t >= 2 else 4 if good_t == 1 else -6)
        score += rules['guru_score'].get(str(guru_h), 0) + rules['sani_score'].get(str(sani_h), 0)
        score = max(25, min(95, score))
        H = rules['house'][str(house)]
        lines = [rnd.choice(H['general']),
                 rnd.choice(rules['tara'][TARA[tara_main]]),
                 rnd.choice(H['money'] if house in (2, 11, 6, 10) else H['relations'] if house in (5, 7, 4) else H['health'] if house in (8, 12, 1) else H['work']),
                 rnd.choice(rules['day'][VAARAM[wd]]).replace('{நல்லநேரம்}', NALLA[wd]).replace('{ராகு}', RAHU[wd])]
        if house == 8:   # சந்திராஷ்டமம்
            lines[0] = rnd.choice(rules['chandrashtamam'])
        out.append({'rasi': RASI[r], 'stars': ' · '.join(NAK[n] for n in RASI_NAK[r]), 'house': house,
                    'tara': TARA[tara_main], 'score': score, 'lines': lines,
                    'label': 'மிக நல்ல நாள்' if score >= 75 else 'நல்ல நாள்' if score >= 55 else 'சுமாரான நாள்' if score >= 40 else 'கவனமான நாள்'})
    return out

def build(date_ist):
    rules = json.loads(RULES.read_text(encoding='utf-8'))
    P = positions(date_ist)
    return {'date': date_ist.strftime('%Y-%m-%d'), 'panchangam': panchangam(date_ist, P), 'rasi': palan(date_ist, P, rules)}

if __name__ == '__main__':
    import sys
    d = dt.date.today() if len(sys.argv) < 2 else dt.date.fromisoformat(sys.argv[1])
    print(json.dumps(build(d), ensure_ascii=False, indent=1)[:3000])
