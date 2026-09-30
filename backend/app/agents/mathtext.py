"""Turn LaTeX-style maths into plain Unicode notation that prints cleanly in the worksheet PDF.

The generator is asked to write x², √2, ¾, ∠ABC directly; this is the safety net for anything like
\\frac{3}{4}, x^{2} or $\\sqrt{2}$ that slips through."""
import re

_SUP = str.maketrans("0123456789+-=()niTx", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵀˣ")
_SUB = str.maketrans("0123456789+-=()aeoxnimkt", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₙᵢₘₖₜ")
_SCRIPT_CHARS = set("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵀˣ₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₒₓₙᵢₘₖₜ")
_SYMBOLS = {
    r"\times": "×", r"\div": "÷", r"\cdot": "·", r"\pm": "±", r"\mp": "∓", r"\leq": "≤", r"\le": "≤",
    r"\geq": "≥", r"\ge": "≥", r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\equiv": "≡", r"\pi": "π",
    r"\theta": "θ", r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\Delta": "Δ",
    r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ", r"\omega": "ω", r"\phi": "φ", r"\angle": "∠",
    r"\triangle": "△", r"\degree": "°", r"\circ": "°", r"\infty": "∞", r"\parallel": "∥", r"\perp": "⊥",
    r"\cong": "≅", r"\sim": "∼", r"\therefore": "∴", r"\because": "∵", r"\rightarrow": "→", r"\to": "→",
    r"\Rightarrow": "⇒", r"\leftrightarrow": "↔", r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\cup": "∪",
    r"\cap": "∩", r"\emptyset": "∅", r"\sum": "Σ", r"\%": "%", r"\,": " ", r"\;": " ", r"\!": "", r"\quad": " ",
}
_FUNCS = ("sin", "cos", "tan", "cot", "sec", "cosec", "csc", "log", "ln", "lim", "max", "min")


def _group(s: str, i: int) -> tuple[str, int]:
    """Read a {…} group (with nesting) or a single character starting at s[i]."""
    if i < len(s) and s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    return (s[i], i + 1) if i < len(s) else ("", i)


def _wrap(x: str) -> str:
    return x if re.fullmatch(r"[\w.√π]+", x) else f"({x})"


def _convert(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s.startswith(("\\frac", "\\dfrac", "\\tfrac"), i):
            i = s.index("frac", i) + 4
            num, i = _group(s, i)
            den, i = _group(s, i)
            out.append(f"{_wrap(_convert(num))}/{_wrap(_convert(den))}")
        elif s.startswith("\\sqrt", i):
            i += 5
            root = ""
            if i < len(s) and s[i] == "[":
                j = s.find("]", i)
                root, i = s[i + 1:j].translate(_SUP), j + 1
            body, i = _group(s, i)
            out.append(f"{root}√{_wrap(_convert(body))}")
        elif s[i] in "^_":
            op = s[i]
            if s.startswith("\\", i + 1):  # ^\circ, _\alpha: the script is a command, not a single character
                m = re.match(r"\\[A-Za-z]+", s[i + 1:])
                body, i = (m.group(0), i + 1 + len(m.group(0))) if m else _group(s, i + 1)
            else:
                body, i = _group(s, i + 1)
            if op == "^" and body in ("\\circ", "\\degree", "°", "o"):
                out.append("°")
                continue
            body = _convert(body)
            table = _SUP if op == "^" else _SUB
            conv = body.translate(table)
            if conv and all(c in _SCRIPT_CHARS for c in conv):
                out.append(conv)
            else:
                out.append(f"{op}({body})" if len(body) > 1 else f"{op}{body}")
        elif s.startswith("\\text", i) or s.startswith("\\mathrm", i) or s.startswith("\\mathbf", i):
            i = s.index("{", i)
            body, i = _group(s, i)
            out.append(_convert(body))
        elif s.startswith("\\left", i) or s.startswith("\\right", i):
            i += 5 if s.startswith("\\left", i) else 6
        elif s[i] == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", s[i:], re.S)
            if m is None:  # lone trailing backslash
                i += 1
                continue
            cmd = m.group(0)
            if cmd in _SYMBOLS:
                out.append(_SYMBOLS[cmd])
            elif m.group(1) in _FUNCS:
                out.append(m.group(1))
            elif m.group(1) in "{}()[]":
                out.append(m.group(1))
            else:
                out.append(m.group(1))
            i += len(cmd)
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def to_plain_math(text: str) -> str:
    if not text or ("\\" not in text and "^" not in text and "$" not in text and "_{" not in text):
        return text
    t = re.sub(r"\$\$(.+?)\$\$|\$(.+?)\$|\\\((.+?)\\\)|\\\[(.+?)\\\]",
               lambda m: _convert(next(g for g in m.groups() if g is not None)), text, flags=re.S)
    if "\\" in t or "^" in t or "_{" in t:
        t = _convert(t)
    return re.sub(r"[ \t]{2,}", " ", t)


# ------------------------------------------------------------------------------------------ layout
# Worked answers that arrive as one long line ("Given u = 0, v = 20. Using v = u + at: 20 = 0 + 10a, a = 2 m/s².")
# are hard for students to follow. These helpers put each step, point or part on its own line. They leave text
# that already has line breaks alone, so a teacher's own layout is never changed.

_MARKER = r"(?:\d{1,2}[.)]|\([a-z]\)|\([ivx]{1,4}\)|[a-d]\))"
_STEP_WORDS = (r"(?:Using|Applying|Substitut\w*|Putting|Simplif\w*|Therefore|Hence|Thus|So|Now|Then|Rearrang\w*|"
               r"Multiply\w*|Divid\w*|Taking|Take|Final answer|Answer|अतः|इसलिए|सूत्र|उत्तर)")
_INTRO_COLON = re.compile(r"^((?:Using|Applying|Substituting|Putting|From|सूत्र)\b[^:\n]{0,80}?):\s+(?=\S)")


def _top_level_split(line: str, sep: str = ",") -> list[str]:
    """Split on commas that are not inside brackets."""
    parts, depth, cur = [], 0, ""
    for i, ch in enumerate(line):
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch == sep and depth == 0 and line[i + 1:i + 2] == " ":
            parts.append(cur.strip())
            cur = ""
            continue
        cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def _marker_positions(text: str) -> list[int]:
    """Start positions of real list markers: outside brackets (so '(2 × 5)' is not item '5)'), and numbered ones
    counting up 1, 2, 3 … in order."""
    good, expect = [], 1
    for m in re.finditer(rf"(?:(?<=\s)|^){_MARKER}(?=\s)", text):
        before = text[:m.start()]
        if before.count("(") - before.count(")") > 0:
            continue  # inside brackets: part of a calculation
        num = re.match(r"\d+", m.group(0))
        if num:
            if int(num.group(0)) != expect:
                continue
            expect += 1
        good.append(m.start())
    return good


def _break_markers(text: str) -> str | None:
    """'1) … 2) … 3) …' or '(a) … (b) …' → one item per line. None when there aren't at least two markers."""
    starts = _marker_positions(text)
    if len(starts) < 2:
        return None
    pieces, prev = [], 0
    for s in starts:
        pieces.append(text[prev:s])
        prev = s
    pieces.append(text[prev:])
    out = "\n".join(p.strip() for p in pieces if p.strip())
    # A closing note after the last item ("Here, u = initial velocity …") gets its own line.
    out = re.sub(r"(?<=[.।])\s+(?=(?:Here|Where|Note|यहाँ|जहाँ)\b)", "\n", out)
    return "\n".join(line.strip().rstrip(",;").strip() for line in out.split("\n") if line.strip())


def layout_answer(text: str) -> str:
    t = (text or "").strip()
    if not t or "\n" in t or len(t) < 70:
        return t
    listed = _break_markers(t)
    if listed:
        return listed
    if "=" not in t:
        return t  # plain prose: leave as a paragraph
    # Worked solution: one sentence per line, then split step words, "Using …:" intros and equation chains.
    t = re.sub(r"(?<=[.।])\s+(?=[A-Zऀ-ॿ(−-])", "\n", t)
    t = re.sub(rf"(?<=[,;])\s+(?={_STEP_WORDS}\b)", "\n", t, flags=re.I)
    lines: list[str] = []
    for line in t.split("\n"):
        line = _INTRO_COLON.sub(lambda m: m.group(1) + ":\n", line.strip())
        for sub in line.split("\n"):
            is_given = re.match(r"(?i)\s*(given|दिया)", sub)
            parts = _top_level_split(sub)
            if not is_given and len(parts) > 1 and all("=" in p for p in parts):
                lines.extend(parts)
            else:
                lines.append(sub.strip())
    return "\n".join(line.rstrip(",;").strip() for line in lines if line.strip())


def layout_question(text: str) -> str:
    """Multi-part questions: put (a), (b), (c) … on their own lines."""
    t = (text or "").strip()
    if "\n" in t:
        return t
    parts = list(re.finditer(r"(?<=\s)\((?:[a-e]|i{1,3}|iv|v)\)\s", t))
    if len(parts) < 2:
        return t
    return re.sub(r"\s+(?=\((?:[a-e]|i{1,3}|iv|v)\)\s)", "\n", t)


def normalize_content(content: dict) -> dict:
    """Apply to every text field of a worksheet: plain maths notation, then readable line layout."""
    for key in ("title", "instructions"):
        if isinstance(content.get(key), str):
            content[key] = to_plain_math(content[key])
    for sec in content.get("sections", []):
        for q in sec.get("questions", []):
            q["text"] = layout_question(to_plain_math(q.get("text", "")))
            q["options"] = [to_plain_math(o) for o in q.get("options", [])]
            answer = to_plain_math(q.get("answer", ""))
            # MCQ answers must stay identical to one option, so only written answers are laid out.
            q["answer"] = answer if q["options"] else layout_answer(answer)
    return content
