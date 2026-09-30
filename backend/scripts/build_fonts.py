"""Build the single worksheet font (PSA Sans) from the Noto sources in app/fonts.

ReportLab shapes each word with one font, so a word that mixes scripts (√2, △ABC, "(irrational)" inside a
Hindi sentence) breaks if its characters come from different fonts. One merged font avoids that entirely:
Latin/Greek from Noto Sans, Devanagari (with its shaping rules) from Noto Sans Devanagari, and maths
symbols from Noto Sans Math.

    .venv\\Scripts\\python -m pip install fonttools
    .venv\\Scripts\\python -m scripts.build_fonts

The outputs (app/fonts/PSASans-Regular.ttf, PSASans-Bold.ttf) are committed, so the app needs no fontTools.
All sources are under the SIL Open Font License 1.1."""
from pathlib import Path

from fontTools import subset
from fontTools.merge import Merger
from fontTools.ttLib import TTFont

FONTS = Path(__file__).resolve().parent.parent / "app" / "fonts"
TMP = FONTS / "_build"

# Maths symbols to take from Noto Sans Math (only what Noto Sans lacks is used; Sans wins on overlaps).
MATH_RANGES = [
    (0x2070, 0x209F),  # superscripts and subscripts
    (0x2100, 0x214F),  # letterlike symbols
    (0x2150, 0x218F),  # number forms (⅓ ⅔ …)
    (0x2190, 0x21FF),  # arrows
    (0x2200, 0x22FF),  # mathematical operators: √ ∛ ≤ ≥ ∠ ∥ ⊥ ≅ ∴ ∵ …
    (0x2300, 0x23FF),  # misc technical
    (0x25A0, 0x25FF),  # geometric shapes: △ □ ○
    (0x27C0, 0x27EF), (0x2980, 0x29FF), (0x2A00, 0x2AFF),  # more maths operators
    (0x0391, 0x03C9),  # Greek (fallback only)
]


def _prepare(src: str, out: Path, unicodes: list[int] | None = None) -> Path:
    font = TTFont(FONTS / src)
    opts = subset.Options()
    opts.hinting = False  # hinting programs can't be merged; unhinted text prints fine
    opts.layout_features = ["*"]  # keep every shaping feature (Devanagari needs many)
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.glyph_names = True
    opts.drop_tables += ["MATH", "DSIG"]
    sub = subset.Subsetter(opts)
    if unicodes is None:
        sub.populate(unicodes=font.getBestCmap().keys())
    else:
        cmap = font.getBestCmap()
        sub.populate(unicodes=[u for u in unicodes if u in cmap])
    sub.subset(font)
    font.save(out)
    return out


def build(weight: str) -> Path:
    TMP.mkdir(exist_ok=True)
    math_codes = [u for a, b in MATH_RANGES for u in range(a, b + 1)]
    parts = [
        _prepare(f"NotoSans-{weight}.ttf", TMP / f"sans-{weight}.ttf"),
        _prepare(f"NotoSansDevanagari-{weight}.ttf", TMP / f"deva-{weight}.ttf"),
        _prepare("NotoSansMath-Regular.ttf", TMP / "math.ttf", math_codes),
    ]
    merged = Merger().merge([str(p) for p in parts])
    name = merged["name"]
    for rec in name.names:
        if rec.nameID in (1, 16):
            rec.string = "PSA Sans"
        elif rec.nameID == 4:
            rec.string = f"PSA Sans {weight}"
        elif rec.nameID == 6:
            rec.string = f"PSASans-{weight}"
    out = FONTS / f"PSASans-{weight}.ttf"
    merged.save(out)
    return out


if __name__ == "__main__":
    for w in ("Regular", "Bold"):
        p = build(w)
        f = TTFont(p)
        print(p.name, f["maxp"].numGlyphs, "glyphs", p.stat().st_size // 1024, "KB")
    for p in TMP.glob("*"):
        p.unlink()
    TMP.rmdir()
