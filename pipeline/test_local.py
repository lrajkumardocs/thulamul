"""API key இல்லாமல் மூலங்களை மட்டும் சோதிக்க:  python pipeline/test_local.py"""
import yaml, feedparser, pathlib
src = yaml.safe_load((pathlib.Path(__file__).parent / "sources.yaml").read_text(encoding="utf-8"))
for s in src:
    f = feedparser.parse(s["url"])
    print(f"{'OK ' if f.entries else 'XX '} {s['name']:<18} {len(f.entries):>3} items  {f.entries[0].title[:60] if f.entries else ''}")
