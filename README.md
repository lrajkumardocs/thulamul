# துலாமுள் — Session 1: செய்தி இயந்திரம்

இந்த folder-ல் இருப்பது: ஒவ்வொரு 30 நிமிடமும் தானாக மூலங்களைப் படித்து, Claude மூலம் 5-வரி தமிழ்ச் செய்தி எழுதி, ஆடியோ உருவாக்கி, `data/feed.json`-ல் வெளியிடும் இயந்திரம். செலவு: Claude API மட்டும் (≈ ₹2,000–3,000/மாதம்). மற்றவை (GitHub Actions, Edge TTS, Telegram) ₹0.

நீங்கள் செய்ய வேண்டியது மொத்தம் **5 படி, ~25 நிமிடம்.** ஒரு முறை மட்டும்.

---

## படி 1 — GitHub கணக்கு + repo (5 நிமிடம்)

1. github.com → Sign up (இருந்தால் Sign in).
2. மேலே **+** → **New repository** → பெயர் `thulamul` → **Private** → Create.
3. அந்தப் பக்கத்தில் **"uploading an existing file"** என்ற link → இந்த folder-ல் உள்ள எல்லாவற்றையும் (folder-களுடன்) drag & drop → **Commit changes**.
   - Mac-ல் `.github` folder மறைந்திருக்கும்: Finder-ல் `Cmd+Shift+.` அழுத்தினால் தெரியும்.
   - Drag & drop-ல் folder வரவில்லை என்றால்: Terminal-ல்
     ```
     cd ~/Downloads/thulamul
     git init && git add . && git commit -m "session 1"
     git branch -M main
     git remote add origin https://github.com/<உங்கள்-பெயர்>/thulamul.git
     git push -u origin main
     ```

## படி 2 — Anthropic API key (5 நிமிடம், ₹420)

1. console.anthropic.com → Sign up (Google-ல்).
2. இடது **Billing** → Add credits → $5.
3. **API Keys** → Create Key → பெயர் `thulamul` → key-ஐ copy. **இது ஒரு முறை மட்டும் தெரியும்.** யாருக்கும் அனுப்பாதீர்கள்; எனக்கும்.

## படி 3 — Telegram bot (3 நிமிடம்)

1. Telegram-ல் **@BotFather** தேடி → `/newbot` → பெயர்: `Thulamul` → username: `thulamul_desk_bot` (ஏதேனும் _bot-ல் முடியணும்).
2. வரும் **token** (எண்கள்:எழுத்துகள்) copy.
3. உங்கள் புதிய bot-ஐ திறந்து **/start** அனுப்புங்கள் (இது முக்கியம்).
4. உங்கள் chat id: Telegram-ல் **@userinfobot** தேடி → /start → வரும் **Id** எண் copy.

## படி 4 — Secrets சேர்த்தல் (3 நிமிடம்)

GitHub → உங்கள் `thulamul` repo → **Settings** → இடது **Secrets and variables → Actions** → **New repository secret** — மூன்று முறை:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | படி 2-ன் key |
| `TELEGRAM_BOT_TOKEN` | படி 3-ன் token |
| `TELEGRAM_CHAT_ID` | படி 3-ன் Id எண் |

## படி 5 — முதல் ஓட்டம் (2 நிமிடம்)

1. Repo → மேலே **Actions** → இடது **thulamul-pipeline** → வலது **Run workflow** → Run.
2. 2–3 நிமிடத்தில் பச்சை ✓. Click செய்து log பாருங்கள் — `[publish] …` வரிகள் = வெளியான செய்திகள்; `[hold]` = Telegram-க்கு வந்தவை.
3. `data/feed.json` தானாக repo-ல் update ஆகும். இனி 30 நிமிடத்திற்கு ஒரு முறை தானாக.

**சோதனைப் பக்கம்:** Settings → Pages → Source: Deploy from branch → main / (root) → Save. 1 நிமிடத்தில் `https://<பெயர்>.github.io/thulamul/web/` — feed-ஐ ஆடியோவுடன் பார்க்கலாம். (Session 3-ல் இதுவே v10 வடிவமைப்பாக மாறும்.)

---

## தினசரி நீங்கள் செய்வது

- Telegram-ல் ⚖️ **சரிபார்க்க** என்று வரும் செய்திக்கு `✔ abc123def456` அல்லது `✘ abc123def456` என்று பதில் (id அந்தச் செய்தியிலேயே இருக்கும்; copy-paste). 6 மணி பதில் இல்லை என்றால் தானாகக் கைவிடப்படும்.
- **தலையங்கம்:** bot-க்கு இப்படி அனுப்புங்கள் —
  ```
  தலையங்கம்: முள் நடுவில் நிற்பது கோழைத்தனம் அல்ல
  ஒரு தராசின் முள் நடுவில் நிற்கும்போது…
  ```
  அடுத்த ஓட்டத்தில் (≤30 நிமிடம்) வெளியாகும். Admin web பக்கம் Session 6-ல்.

## மாற்ற விரும்பினால்

- **மூலம் சேர்க்க/நீக்க:** `pipeline/sources.yaml` — ஒரு வரி.
- **எழுத்து விதிகள்:** `pipeline/prompts/news_5line.md` — தமிழில் இருக்கிறது; நீங்களே திருத்தலாம்.
- **குரல்:** workflow-ல் `TTS_VOICE` — `ta-IN-PallaviNeural` (பெண்) / `ta-IN-ValluvarNeural` (ஆண்).
- **செலவு கட்டுப்பாடு:** `MAX_NEW_PER_RUN` — ஓட்டத்திற்கு அதிகபட்ச செய்திகள் (12 × 48 ஓட்டம் = நாளுக்கு 576 உச்சம்; உண்மையில் 40–80 வரும்).

## பிரச்சனை என்றால்

Actions log-ன் சிவப்பு வரியை copy செய்து எனக்கு அனுப்புங்கள். பொதுவானவை:
- `[fetch] X: பிழை` — அந்த RSS முகவரி மாறிவிட்டது; sources.yaml-ல் நீக்கு/மாற்று.
- `[claude] பிழை authentication` — API key தவறு/credit இல்லை.
- Telegram வரவில்லை — bot-க்கு /start அனுப்பவில்லை, அல்லது chat id தவறு.
