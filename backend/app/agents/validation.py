"""Deterministic worksheet validation. Runs after generation and after every manual edit.

A 'failed' check blocks release (the worksheet goes to review); a 'warning' is shown to the
reviewer but does not block Fully automated release."""
from ..services.common import SECTION_LABELS
from ..services.rag import devanagari_share, tokenize

SECTION_LETTERS = "ABCDEFGHIJ"
GROUNDING_MIN = 0.35   # share of a question's content words found in its cited passages
WEAK_GROUNDING_BLOCK = 0.2  # more than this share of weakly grounded questions fails the check
DUPLICATE_JACCARD = 0.7


def question_refs(content: dict) -> list[tuple[str, str, dict]]:
    """[(ref like 'A-1', section type, question)] in worksheet order."""
    out = []
    for si, sec in enumerate(content.get("sections", [])):
        for qi, q in enumerate(sec.get("questions", []), start=1):
            out.append((f"{SECTION_LETTERS[si]}-{qi}", sec.get("type", ""), q))
    return out


def _check(cid: str, label: str, status: str, detail: str, refs: list[str] | None = None) -> dict:
    return {"id": cid, "label": label, "status": status, "detail": detail, "refs": refs or []}


def validate(content: dict, settings: dict, passage_text: dict[str, str], scope_ids: set[str] | None = None) -> dict:
    """passage_text maps source ids ('C12') to passage text. scope_ids, when given, is the set of
    passages inside the confirmed exam syllabus; citing anything else fails the scope check."""
    checks = []
    qs = question_refs(content)
    manual = bool(content.get("_manual"))  # a teacher edited this worksheet by hand

    # 1. Structure matches settings. When a teacher has edited the worksheet, a different number of questions is
    # their choice (a warning); broken MCQs and empty questions are still errors.
    want = {k: v for k, v in settings["counts"].items() if v}
    got: dict[str, int] = {}
    for sec in content.get("sections", []):
        got[sec.get("type")] = got.get(sec.get("type"), 0) + len(sec.get("questions", []))
    diffs = [f"{SECTION_LABELS.get(k, k)} {got.get(k, 0)} of {n}" for k, n in want.items() if got.get(k, 0) != n]
    extra = [SECTION_LABELS.get(k, k) for k in got if k not in want and got[k]]
    bad_mcq = [ref for ref, t, q in qs if t == "mcq" and (len(q.get("options", [])) != 4
                                                          or any(not o.strip() for o in q.get("options", []))
                                                          or q.get("answer", "").strip() not in [o.strip() for o in q.get("options", [])])]
    empty = [ref for ref, _, q in qs if not q.get("text", "").strip()]
    parts = []
    if diffs:
        parts.append(("question counts changed by a teacher: " if manual else "counts differ: ") + ", ".join(diffs))
    if extra:
        parts.append(("sections added by a teacher: " if manual else "unexpected sections: ") + ", ".join(extra))
    if bad_mcq:
        parts.append("MCQs need four filled-in options with the correct answer among them")
    if empty:
        parts.append("empty questions")
    if bad_mcq or empty or ((diffs or extra) and not manual):
        checks.append(_check("structure", "Structure matches settings", "failed", "; ".join(parts), bad_mcq + empty))
    elif diffs or extra:
        checks.append(_check("structure", "Structure matches settings", "warning", "; ".join(parts)))
    else:
        checks.append(_check("structure", "Structure matches settings", "passed", f"{len(qs)} questions"))

    # 2. Grounded in approved PDFs. Word overlap only works when questions and passages share a script;
    # a Hindi worksheet built from English PDFs (translated) is checked by its citations alone.
    # Questions a teacher wrote or reworded are trusted: the teacher is the authority on them.
    all_text = " ".join(q.get("text", "") for _, _, q in qs)
    translated = abs(devanagari_share(all_text) - devanagari_share(" ".join(passage_text.values()))) > 0.5
    uncited, weak = [], []
    for ref, _, q in qs:
        if q.get("origin") == "teacher":
            continue
        ids = [i for i in q.get("source_ids", []) if i in passage_text]
        if not ids:
            uncited.append(ref)
            continue
        if translated or q.get("edited"):
            continue
        words = set(tokenize(q.get("text", "") + " " + q.get("answer", "")))
        if not words:
            continue
        support = set(tokenize(" ".join(passage_text[i] for i in ids)))
        if len(words & support) / len(words) < GROUNDING_MIN:
            weak.append(ref)
    if uncited:
        checks.append(_check("grounding", "Grounded in approved PDFs", "failed",
                             f"{len(uncited)} question(s) cite no approved passage", uncited))
    elif qs and len(weak) / len(qs) > WEAK_GROUNDING_BLOCK:
        checks.append(_check("grounding", "Grounded in approved PDFs", "failed",
                             f"{len(weak)} question(s) are weakly supported by their cited passages", weak))
    elif weak:
        checks.append(_check("grounding", "Grounded in approved PDFs", "warning",
                             f"{len(weak)} question(s) weakly supported; check them", weak))
    else:
        checks.append(_check("grounding", "Grounded in approved PDFs", "passed",
                             "every question cites its source" + (" (translated worksheet: citations checked)" if translated else "")))

    # 3. No duplicate questions
    dup = []
    toks = [(ref, set(tokenize(q.get("text", "")))) for ref, _, q in qs]
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            a, b = toks[i][1], toks[j][1]
            if a and b and len(a & b) / len(a | b) >= DUPLICATE_JACCARD:
                dup.append(f"{toks[i][0]} ≈ {toks[j][0]}")
    checks.append(_check("duplicates", "No duplicate questions", "failed" if dup else "passed",
                         ", ".join(dup) if dup else "all questions distinct",
                         [r for pair in dup for r in pair.split(" ≈ ")]))

    # 4. Within the exam syllabus: the generator's own flags, plus a hard check that every cited
    # passage lies inside the confirmed exam syllabus scope.
    flagged = [(ref, q.get("review_note") or "flagged as outside the syllabus") for ref, _, q in qs if q.get("outside_syllabus")]
    if scope_ids is not None:
        for ref, _, q in qs:
            outside = [i for i in q.get("source_ids", []) if i not in scope_ids]
            if outside and not q.get("outside_syllabus"):
                flagged.append((ref, f"cites material outside the exam syllabus ({', '.join(outside)})"))
    label = "Within exam syllabus" if scope_ids is not None else "Out-of-scope check"
    if flagged:
        detail = "; ".join(f"{ref}: {note}" for ref, note in flagged)
        checks.append(_check("scope", label, "failed", detail, [r for r, _ in flagged]))
    else:
        checks.append(_check("scope", label, "passed", "all questions within the syllabus"))

    # 5. Answer key
    if settings.get("answer_key"):
        missing = [ref for ref, _, q in qs if not q.get("answer", "").strip()]
        checks.append(_check("answers", "Answer key complete", "failed" if missing else "passed",
                             f"{len(missing)} question(s) have no answer" if missing else "every question answered", missing))

    # 6. Difficulty mix (advisory)
    target = settings.get("difficulty", {})
    if qs and target:
        n = len(qs)
        actual = {lvl: round(100 * sum(1 for _, _, q in qs if q.get("difficulty") == lvl) / n) for lvl in target}
        off = [lvl for lvl, pct in target.items() if abs(actual.get(lvl, 0) - pct) > 15]
        mix = " / ".join(f"{actual[lvl]}% {lvl}" for lvl in target)
        checks.append(_check("difficulty", "Difficulty mix", "warning" if off else "passed", mix))

    failed = [c for c in checks if c["status"] == "failed"]
    return {"passed": not failed, "checks": checks,
            "summary": "Passed" if not failed else f"{len(failed)} check(s) failed"}
