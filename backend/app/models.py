"""Data model. Scheduling, matching, dedup and delivery state are plain relational data;
only worksheet content comes from the model."""
from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="teacher")  # admin | teacher | parent
    class_access: Mapped[list] = mapped_column(JSON, default=list)  # class ids a teacher may see
    student_ids: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)  # a parent's children
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | None] = mapped_column(JSON)


class SchoolClass(Base):
    __tablename__ = "classes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)  # "Class 9"
    grade: Mapped[str] = mapped_column(String(20))  # "9" — matched against date sheet / student rows
    academic_year: Mapped[str] = mapped_column(String(20), default="2026–27")
    sections: Mapped[str] = mapped_column(String(80), default="A")  # "A, B"
    automation: Mapped[str] = mapped_column(String(20), default="draft")  # draft | active | paused
    release_mode: Mapped[str] = mapped_column(String(20), default="review")  # review | auto
    channel_email: Mapped[bool] = mapped_column(Boolean, default=True)
    channel_whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    worksheet_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # overrides global
    datesheet_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    datesheet_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    datesheet_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    datesheet_issues: Mapped[list] = mapped_column(JSON, default=list)
    # Parsed rows awaiting confirmation. Live exams only change when the admin confirms.
    datesheet_pending: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Exam syllabus: the school's portion for this exam cycle, uploaded with the date sheet. It is the
    # hard scope boundary for worksheets. scope = {subject_lower: {subject, text, chapters, topics}}.
    syllabus_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    syllabus_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    syllabus_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    syllabus_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    syllabus_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    syllabus_pending: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    exams: Mapped[list["Exam"]] = relationship(back_populates="school_class", cascade="all, delete-orphan")
    subjects: Mapped[list["Subject"]] = relationship(back_populates="school_class", cascade="all, delete-orphan")
    students: Mapped[list["Student"]] = relationship(back_populates="school_class", cascade="all, delete-orphan")

    def section_list(self) -> list[str]:
        return [s.strip().upper() for s in self.sections.split(",") if s.strip()]


class Exam(Base):
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    exam_code: Mapped[str] = mapped_column(String(60))  # EX9-MATH-001
    subject_name: Mapped[str] = mapped_column(String(120))
    sections: Mapped[str] = mapped_column(String(80), default="")  # "" = every section of the class
    exam_date: Mapped[date] = mapped_column(Date, index=True)
    exam_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # false once removed by a newer date sheet
    school_class: Mapped[SchoolClass] = relationship(back_populates="exams")

    def section_list(self) -> list[str]:
        return [s.strip().upper() for s in self.sections.split(",") if s.strip()]


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("class_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    worksheet_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # overrides class
    school_class: Mapped[SchoolClass] = relationship(back_populates="subjects")
    documents: Mapped[list["Document"]] = relationship(back_populates="subject", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20), default="chapter")  # syllabus | chapter
    chapter: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    extraction: Mapped[str] = mapped_column(String(20), default="ok")  # ok | empty | failed
    uploaded_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    subject: Mapped[Subject] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)
    document: Mapped[Document] = relationship(back_populates="chunks")


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("class_id", "student_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    student_code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(255))
    section: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    school_class: Mapped[SchoolClass] = relationship(back_populates="students")


class Job(Base):
    """A durable unit of work. business_key is unique, so a retried scheduler run or a restart
    can never create the same job twice."""
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40))  # CREATE_WORKSHEET | SHARE_WORKSHEET | PARENT_WORKSHEET
    business_key: Mapped[str] = mapped_column(String(400), unique=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)
    worksheet_id: Mapped[int | None] = mapped_column(ForeignKey("worksheets.id", ondelete="SET NULL"), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(120))
    sections: Mapped[str] = mapped_column(String(80), default="")
    exam_date: Mapped[date] = mapped_column(Date)
    trigger_date: Mapped[date] = mapped_column(Date)
    # pending | running | validation-failed | awaiting-approval | released | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="scheduler")  # scheduler | manual
    # Work in flight between worker ticks, e.g. a submitted Batch API request: {"batch_id": ..., "plan": {...}}
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Worksheet(Base):
    __tablename__ = "worksheets"
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)
    create_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject_name: Mapped[str] = mapped_column(String(120))
    sections: Mapped[str] = mapped_column(String(80), default="")
    exam_code: Mapped[str] = mapped_column(String(60))
    exam_date: Mapped[date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # generating | validation-failed | awaiting-approval | released | superseded | cancelled
    status: Mapped[str] = mapped_column(String(30), default="generating", index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    settings_used: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    generator: Mapped[str] = mapped_column(String(80), default="")
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    regeneration_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reused_from_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # copied from another worksheet
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ParentSheet(Base):
    """A practice sheet a parent made for their own child. Private to that child: it never goes through teacher
    review or class delivery, and it is not tied to an exam."""
    __tablename__ = "parent_sheets"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    subject_name: Mapped[str] = mapped_column(String(120))
    chapters: Mapped[list] = mapped_column(JSON, default=list)  # chapter labels chosen by the parent; [] = all
    sections: Mapped[str] = mapped_column(String(20), default="")  # the child's section (printed on the PDF)
    status: Mapped[str] = mapped_column(String(20), default="generating", index=True)  # generating | ready | failed
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    settings_used: Mapped[dict] = mapped_column(JSON, default=dict)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    generator: Mapped[str] = mapped_column(String(80), default="")
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Delivery(Base):
    """One row per worksheet × student × channel. Email and WhatsApp are tracked independently."""
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("worksheet_id", "student_id", "channel"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    worksheet_id: Mapped[int] = mapped_column(ForeignKey("worksheets.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))  # email | whatsapp
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # queued | sending | sent | delivered | retrying | skipped | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255), default="system")
    event: Mapped[str] = mapped_column(String(40), index=True)
    class_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info | warning | error
