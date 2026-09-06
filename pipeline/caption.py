"""
துலாமுள் — கேலிச்சித்திரத்தின் கீழே தமிழ் வசனப் பட்டை (banner) சேர்க்கும்.
நிலையான இடம், நிலையான வடிவம் — ஒவ்வொரு நாளும் ஒரே மாதிரி; மனித வேலை இல்லை.
"""
import os, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "pipeline" / "fonts"
PAPER = (243, 242, 238)
INK = (22, 27, 36)
BRASS = (168, 134, 47)
GREY = (140, 145, 155)

def _font(name, size):
    p = FONT_DIR / name
    try:
        return ImageFont.truetype(str(p), size)
    except Exception:
        return ImageFont.load_default()

def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def add_caption(img_path, caption, date_str, out_path=None):
    """படத்தின் கீழே வசனப் பட்டை. தோல்வி → அசல் படமே."""
    try:
        im = Image.open(img_path).convert("RGB")
        W = im.width
        pad = int(W * 0.045)
        fs = max(20, int(W * 0.040))                   # வசன எழுத்து அளவு
        fs_small = max(12, int(W * 0.019))
        f = _font("NotoSerifTamil.ttf", fs)
        fsm = _font("NotoSerifTamil.ttf", fs_small)

        # கையொப்பம் — நிரந்தர இடம் (கீழ் வலது). signature.png இருந்தால் அது; இல்லையெனில் எழுத்து.
        sig_png = FONT_DIR / "signature.png"
        margin = int(W * 0.035)
        if sig_png.exists():
            try:
                sg = Image.open(sig_png).convert("RGBA")
                tw = int(W * 0.13)
                sg = sg.resize((tw, max(1, int(sg.height * tw / sg.width))), Image.LANCZOS)
                im.paste(sg, (margin, im.height - margin - sg.height), sg)          # கீழ் இடது மூலை (ஆல்பா)
            except Exception as ex:
                print("[sig] பிழை", str(ex)[:80])
        else:
            sd = ImageDraw.Draw(im, "RGBA")
            sig = _font("Kavivanar-Regular.ttf", max(18, int(W * 0.042)))
            st = "Mr. X"
            sw = sd.textlength(st, font=sig)
            sd.text((margin, im.height - margin - int(W * 0.055)), st, font=sig, fill=INK)

        tmp = ImageDraw.Draw(im)
        lines = _wrap(tmp, (caption or "").strip(), f, W - 2 * pad)
        while len(lines) > 3 and fs > 18:              # மூன்று வரிக்குள் அடங்கும்வரை சுருக்கு
            fs -= 2
            f = _font("MeeraInimai-Regular.ttf", fs)
            lines = _wrap(tmp, (caption or "").strip(), f, W - 2 * pad)

        line_h = int(fs * 1.75)
        band = pad + len(lines) * line_h + int(fs_small * 2.4) + pad // 2
        out = Image.new("RGB", (W, im.height + band), PAPER)
        out.paste(im, (0, 0))
        d = ImageDraw.Draw(out)

        y0 = im.height
        d.line([(pad, y0 + pad // 2), (W - pad, y0 + pad // 2)], fill=INK, width=2)   # மேல் கோடு
        y = y0 + pad
        for ln in lines:
            d.text(((W - d.textlength(ln, font=f)) / 2, y), ln, font=f, fill=INK)
            y += line_h
        y += int(fs_small * 0.3)
        d.line([(W // 2 - int(W * 0.06), y), (W // 2 + int(W * 0.06), y)], fill=BRASS, width=2)  # சிறு பித்தளைக் கோடு
        y += int(fs_small * 0.5)
        d.text((W - pad - d.textlength(date_str, font=fsm), y), date_str, font=fsm, fill=GREY)

        out.save(out_path or img_path, quality=92)
        return True
    except Exception as ex:
        print("[caption] பிழை", str(ex)[:120])
        return False

if __name__ == "__main__":
    import sys
    add_caption(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "சோதனை வசனம்", "6 செப்டம்பர் 2026")
