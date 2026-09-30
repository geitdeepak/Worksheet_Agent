"""Exam syllabus: the school's portion for this exam cycle, per subject.

Schools publish it as a PDF/Word notice or a spreadsheet. Parsing splits it by subject and pulls
out chapter numbers and topic lines; the admin reviews and can edit each subject's scope before
confirming. The confirmed scope is the hard boundary for worksheet generation."""
import io
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from ..config import get_settings
from .tabular import read_table

_CH_RANGE = re.compile(r"(?:chapters?|ch|chs|units?|lessons?|l)\.?\s*[-–:#]?\s*(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})", re.I)
_CH_LIST = re.compile(r"(?:chapters?|ch|chs|units?|lessons?)\.?\s*[-–:#]?\s*((?:\d{1,2}\s*(?:,|&|and)\s*)*\d{1,2})\b", re.I)


_EXCLUDE = re.compile(r"\b(not\s+(?:be\s+)?included|not\s+in\s+(?:the\s+)?syllabus|excluded?|except|excluding|"
                      r"deleted|omitted|omit|not\s+for\s+(?:the\s+)?exam|removed|will\s+not\s+come)\b", re.I)


def split_exclusions(text: str) -> tuple[str, str]:
    """Separate lines that remove material ('Chapter 6 is not included', 'excluding 5.3') from the rest."""
    keep, drop = [], []
    for line in text.splitlines():
        (drop if _EXCLUDE.search(line) else keep).append(line)
    return "\n".join(keep), "\n".join(drop)


def _chapter_numbers(text: str) -> list[int]:
    found: set[int] = set()
    for a, b in _CH_RANGE.findall(text):
        a, b = int(a), int(b)
        if 0 < a <= b <= 40:
            found.update(range(a, b + 1))
    for group in _CH_LIST.findall(text):
        for n in re.findall(r"\d{1,2}", group):
            if 0 < int(n) <= 40:
                found.add(int(n))
    return sorted(found)


def extract_chapters(text: str) -> list[int]:
    """Chapters in scope: those named in the text minus those named on exclusion lines."""
    included, excluded = split_exclusions(text)
    return sorted(set(_chapter_numbers(included)) - set(_chapter_numbers(excluded)))


def extract_excluded(text: str) -> list[int]:
    return _chapter_numbers(split_exclusions(text)[1])


def extract_topics(text: str) -> list[str]:
    topics = []
    for part in re.split(r"[\n;•]|,(?![^()]*\))", text):
        t = re.sub(r"^[\s\-\*\d\.\):]+", "", part).strip(" .")
        if 3 <= len(t) <= 120 and t.lower() not in {x.lower() for x in topics}:
            topics.append(t)
    return topics[:60]


def make_entry(subject: str, text: str) -> dict:
    text = text.strip()
    included, _ = split_exclusions(text)
    return {"subject": subject, "text": text, "chapters": extract_chapters(text), "excluded_chapters": extract_excluded(text),
            "topics": extract_topics(included)}


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml")
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ElementTree.fromstring(xml)
    lines = []
    for p in root.iter(f"{ns}p"):
        lines.append("".join(t.text or "" for t in p.iter(f"{ns}t")))
    return "\n".join(lines)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    if text.strip():
        return text
    from ..agents.llm import transcribe_pdf  # scanned notice
    return transcribe_pdf(data)


def _split_by_subject(text: str, subjects: list[str]) -> dict[str, str]:
    """Assign lines to the most recent subject heading. A heading is a line that starts with a known
    subject name (e.g. 'Mathematics:', 'MATHEMATICS – Ch 1, 2', '2. Science')."""
    names = sorted({s for s in subjects if s}, key=len, reverse=True)
    out: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        stripped = re.sub(r"^[\s\d\.\)\-•]+", "", line)
        hit = next((n for n in names if re.match(rf"{re.escape(n)}\b", stripped, re.I)), None)
        if hit:
            current = hit
            rest = stripped[len(hit):].strip(" :-–—\t")
            out.setdefault(current, [])
            if rest:
                out[current].append(rest)
        elif current:
            out[current].append(line)
    return {k: "\n".join(v) for k, v in out.items() if v}


def _table_scope(filename: str, data: bytes) -> dict[str, str]:
    rows = read_table(filename, data)
    out: dict[str, list[str]] = {}
    for r in rows:
        subj = str(r.get("subject") or "").strip()
        scope = str(r.get("syllabus") or "").strip()
        if "(example" in subj.lower():
            continue  # template sample row
        if subj and scope:
            out.setdefault(subj, []).append(scope)
    return {k: "\n".join(v) for k, v in out.items()}


def parse_syllabus(filename: str, data: bytes, subjects: list[str]) -> tuple[dict, list[dict], str]:
    """Returns (scope entries keyed by lower-case subject, issues, raw text for display)."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".csv")):
        by_subject = _table_scope(filename, data)
        raw = "\n\n".join(f"{k}: {v}" for k, v in by_subject.items())
    else:
        if name.endswith(".pdf"):
            raw = _pdf_text(data)
        elif name.endswith(".docx"):
            raw = _docx_text(data)
        elif name.endswith(".txt"):
            raw = data.decode("utf-8-sig", errors="replace")
        else:
            raise ValueError("Upload the syllabus as a PDF, Word (.docx), Excel (.xlsx), CSV or text file.")
        by_subject = _split_by_subject(raw, subjects)

    # Match to the canonical subject names used on the date sheet / subjects list.
    canon = {s.lower(): s for s in subjects}
    entries = {}
    for subj, text in by_subject.items():
        key = subj.strip().lower()
        entries[key] = make_entry(canon.get(key, subj.strip()), text)
    issues = [{"subject": s, "message": f"No syllabus found for {s}. Add it below before confirming."}
              for s in subjects if s.lower() not in entries]
    for e in entries.values():
        if not e["chapters"] and len(e["topics"]) < 1:
            issues.append({"subject": e["subject"], "message": f"{e['subject']} · no chapters or topics recognised; check the text."})
    return entries, issues, raw[:20000]


def store_file(class_id: int, filename: str, data: bytes) -> Path:
    folder = get_settings().uploads_dir / f"class_{class_id}" / "syllabus"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:120]
    path = folder / f"{uuid.uuid4().hex[:8]}_{safe}"
    path.write_bytes(data)
    return path


def chapter_number(label: str | None) -> int | None:
    m = re.search(r"(\d{1,2})", label or "")
    return int(m.group(1)) if m else None
