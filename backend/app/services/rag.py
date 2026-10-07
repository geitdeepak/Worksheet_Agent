"""Retrieval over a subject's approved, active PDFs.

BM25 keeps retrieval dependency-free and deterministic; the corpus per subject is small (a
syllabus and a few chapters). Only chunks from active documents of the exam's class + subject
are ever searched, which is what keeps questions inside approved material."""
import math
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Document, Subject

STOP = set("""a an the and or of to in on for with by as at from is are was were be been being this that these
those it its into than then there their they them which who whom what when where why how not no can could
should would will shall may might must do does did done has have had having also such each other more most
very all any some both few many much own same so too only just about above below between after before during
under over again further once here i you he she we our your his her one two three chapter page exercise
है हैं था थे थी का की के में से को और या यह वह ये वे पर एक भी तो ही कि जो लिए नहीं किया कर गया गई तथा इस उस इन उन
अपने अपनी अपना होता होती होते जाता जाती जाते जब तक साथ द्वारा किसी कोई कुछ""".split())
# Latin words, Devanagari words (letters + vowel signs), and numbers.
_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9]+|[ऀ-ॣॱ-ॿ]{2,}|\d+(?:\.\d+)?")


def devanagari_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if "ऀ" <= c <= "ॿ") / len(letters) if letters else 0.0


def tokenize(text: str) -> list[str]:
    return [t for t in (m.group(0).lower() for m in _TOKEN.finditer(text)) if t not in STOP and len(t) > 1]


@dataclass
class Passage:
    chunk_id: int
    document_id: int
    filename: str
    version: int
    kind: str
    chapter: str | None
    page: int
    text: str


class SubjectIndex:
    def __init__(self, passages: list[Passage], k1: float = 1.5, b: float = 0.75):
        self.passages = passages
        self.docs = [tokenize(p.text) for p in passages]
        self.tf = [Counter(d) for d in self.docs]
        self.avgdl = (sum(len(d) for d in self.docs) / len(self.docs)) if self.docs else 0
        df = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def score(self, query_tokens: list[str], i: int) -> float:
        tf, dl = self.tf[i], len(self.docs[i]) or 1
        s = 0.0
        for t in query_tokens:
            f = tf.get(t)
            if f:
                s += self.idf.get(t, 0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s

    def search(self, query: str, k: int = 5) -> list[tuple[Passage, float]]:
        q = tokenize(query)
        scored = [(self.passages[i], self.score(q, i)) for i in range(len(self.passages))]
        scored = [x for x in scored if x[1] > 0]
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


def load_passages(db: Session, subject: Subject) -> list[Passage]:
    rows = db.execute(
        select(Chunk, Document).join(Document, Chunk.document_id == Document.id)
        .where(Document.subject_id == subject.id, Document.active.is_(True))
        .order_by(Document.kind.desc(), Document.chapter, Document.id, Chunk.idx)
    ).all()
    return [Passage(c.id, d.id, d.filename, d.version, d.kind, d.chapter, c.page, c.text) for c, d in rows]


def syllabus_topics(passages: list[Passage], limit: int = 40) -> list[str]:
    """Topic lines from the syllabus documents: short lines, bullets, numbered items, 'Unit'/'Chapter' headings."""
    topics: list[str] = []
    for p in passages:
        if p.kind != "syllabus":
            continue
        for line in p.text.splitlines():
            line = re.sub(r"^[\s•\-\*\d\.\)\(]+", "", line).strip()
            if 4 <= len(line) <= 90 and len(tokenize(line)) >= 1 and line not in topics:
                topics.append(line)
    return topics[:limit]


def scope_passages(passages: list[Passage], scope: dict) -> list[Passage]:
    """Restrict to the exam syllabus: chapters named in the scope, plus chunks that match its topics.
    Full-year syllabus documents are dropped — the exam syllabus replaces them as the boundary."""
    from .syllabus import chapter_number
    content = [p for p in passages if p.kind != "syllabus"] or passages
    excluded = set(scope.get("excluded_chapters") or [])
    content = [p for p in content if chapter_number(p.chapter) not in excluded]  # exclusions always win
    chapters = set(scope.get("chapters") or [])
    labels = set(scope.get("chapter_labels") or [])  # exact document chapter labels (a parent's choice)
    keep: dict[int, Passage] = {}
    if chapters or labels:
        for p in content:
            if chapter_number(p.chapter) in chapters or p.chapter in labels:
                keep[p.chunk_id] = p
    # Topic matching catches material in files without chapter numbers (e.g. 'Physics.pdf').
    topics = scope.get("topics") or []
    if topics and content:
        index = SubjectIndex(content)
        for t in topics:
            hits = index.search(t, k=4)
            if not hits:
                continue
            best = hits[0][1]
            for p, score in hits:
                # Only strong matches; when chapters are named, topic hits must stay inside them
                # unless the passage has no chapter label at all.
                if score >= 0.5 * best and (not chapters or p.chapter is None or chapter_number(p.chapter) in chapters):
                    keep[p.chunk_id] = p
    return [p for p in content if p.chunk_id in keep]


def build_context(db: Session, subject: Subject, budget_chars: int = 120_000,
                  scope: dict | None = None) -> tuple[list[Passage], list[str]]:
    """Choose the passages a worksheet is grounded in.

    With an exam syllabus, only in-scope passages are eligible. Small sets are passed whole (best
    grounding). Larger ones are covered topic by topic, then filled evenly across chapters."""
    passages = load_passages(db, subject)
    if scope:
        passages = scope_passages(passages, scope)
        topics = list(scope.get("topics") or [])
    else:
        topics = syllabus_topics(passages)
    total = sum(len(p.text) for p in passages)
    if total <= budget_chars:
        return passages, topics

    index = SubjectIndex(passages)
    chosen: dict[int, Passage] = {p.chunk_id: p for p in passages if p.kind == "syllabus"}
    used = sum(len(p.text) for p in chosen.values())
    for t in topics:
        for p, _ in index.search(t, k=3):
            if p.chunk_id not in chosen and used + len(p.text) <= budget_chars:
                chosen[p.chunk_id] = p
                used += len(p.text)
    # Round-robin across documents so no chapter is left out.
    by_doc: dict[int, list[Passage]] = {}
    for p in passages:
        by_doc.setdefault(p.document_id, []).append(p)
    progressed = True
    while progressed and used < budget_chars:
        progressed = False
        for plist in by_doc.values():
            while plist and plist[0].chunk_id in chosen:
                plist.pop(0)
            if plist and used + len(plist[0].text) <= budget_chars:
                p = plist.pop(0)
                chosen[p.chunk_id] = p
                used += len(p.text)
                progressed = True
    ordered = [p for p in passages if p.chunk_id in chosen]
    return ordered, topics
