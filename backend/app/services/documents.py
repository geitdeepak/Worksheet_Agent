"""Subject PDF repository: store, extract text, chunk. Old versions are kept (inactive) so every
worksheet can be traced back to the exact material it was built from."""
import re
import uuid
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Chunk, Document, Subject

CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"-\n(\w)", r"\1", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(path: Path) -> list[str]:
    reader = PdfReader(str(path))
    return [_clean(p.extract_text() or "") for p in reader.pages]


def chunk_pages(pages: list[str]) -> list[tuple[int, str]]:
    """Paragraph-aware chunks of ~CHUNK_CHARS with a small overlap. Returns (page, text)."""
    out: list[tuple[int, str]] = []
    for page_no, text in enumerate(pages, start=1):
        if not text:
            continue
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        buf = ""
        for p in paras:
            while len(p) > CHUNK_CHARS:  # very long paragraph: split on sentence boundaries
                cut = p.rfind(". ", 0, CHUNK_CHARS)
                cut = cut + 1 if cut > CHUNK_CHARS // 2 else CHUNK_CHARS
                if buf:
                    out.append((page_no, buf))
                    buf = ""
                out.append((page_no, p[:cut].strip()))
                p = p[cut - CHUNK_OVERLAP if cut > CHUNK_OVERLAP else cut:].strip()
            if len(buf) + len(p) + 2 > CHUNK_CHARS and buf:
                out.append((page_no, buf))
                buf = buf[-CHUNK_OVERLAP:] + "\n" + p if len(buf) > CHUNK_OVERLAP else p
            else:
                buf = f"{buf}\n\n{p}" if buf else p
        if buf:
            out.append((page_no, buf))
    return out


def guess_chapter(filename: str) -> str | None:
    m = re.search(r"(?:chapter|ch|unit)[\s_\-]*0*(\d+)", filename, re.I)
    return f"Chapter {int(m.group(1))}" if m else None


def ingest_pdf(db: Session, subject: Subject, filename: str, data: bytes, *, kind: str | None,
               chapter: str | None, uploaded_by: str) -> Document:
    s = get_settings()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename)[:120]
    folder = s.uploads_dir / f"class_{subject.class_id}" / f"subject_{subject.id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex[:8]}_{safe}"
    path.write_bytes(data)

    if kind is None:
        kind = "syllabus" if "syllabus" in filename.lower() else "chapter"
    # Same file name in the same subject = a new version of that document.
    prev = db.scalars(select(Document).where(Document.subject_id == subject.id, Document.filename == filename)
                      .order_by(Document.version.desc())).first()
    version = (prev.version + 1) if prev else 1
    if prev:
        for d in db.scalars(select(Document).where(Document.subject_id == subject.id, Document.filename == filename)):
            d.active = False

    doc = Document(subject_id=subject.id, filename=filename, stored_path=str(path), kind=kind,
                   chapter=chapter or guess_chapter(filename), version=version, uploaded_by=uploaded_by)
    try:
        pages = extract_pages(path)
    except Exception:
        pages, doc.extraction = [], "failed"
    doc.pages = len(pages)

    from ..agents.llm import transcribe_pdf  # local import: optional dependency path
    from .common import is_hindi_subject
    from .rag import devanagari_share
    garbled = False
    if pages and not any(pages):
        # Scanned PDF with no text layer: try the model's PDF reading as OCR.
        text = transcribe_pdf(data)
        if text:
            pages = [_clean(text)]
    elif pages and is_hindi_subject(subject.name) and devanagari_share(" ".join(pages)) < 0.3:
        # Hindi books often use legacy (non-Unicode) fonts that extract as Latin gibberish.
        text = transcribe_pdf(data)
        if text and devanagari_share(text) >= 0.3:
            pages = [_clean(text)]
        else:
            garbled = True
    chunks = [] if garbled else chunk_pages(pages)
    doc.chars = sum(len(t) for _, t in chunks)
    if doc.extraction != "failed":
        doc.extraction = "garbled" if garbled else ("ok" if chunks else "empty")
    db.add(doc)
    db.flush()
    for i, (page, text) in enumerate(chunks):
        db.add(Chunk(document_id=doc.id, idx=i, page=page, text=text))
    return doc
