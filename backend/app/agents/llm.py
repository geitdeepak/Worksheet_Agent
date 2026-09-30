"""Claude access for the Worksheet Creation Agent.

Uses structured outputs so the worksheet always comes back as schema-valid JSON, adaptive
thinking with a configurable effort, streaming (worksheets are long), and — by default — the
server-side refusal fallback so a policy decline is retried on Anthropic's recommended model."""
import base64
import json
import logging

import anthropic

from ..config import get_settings

log = logging.getLogger("psa.llm")

QUESTION_TYPES = ["mcq", "very_short", "short", "application", "long", "hots"]

WORKSHEET_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "instructions": {"type": "string"},
        "coverage_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"topic": {"type": "string"}, "question_refs": {"type": "array", "items": {"type": "string"}}},
                "required": ["topic", "question_refs"],
                "additionalProperties": False,
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": QUESTION_TYPES},
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "options": {"type": "array", "items": {"type": "string"}},
                                "answer": {"type": "string"},
                                "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                                "topic": {"type": "string"},
                                "source_ids": {"type": "array", "items": {"type": "string"}},
                                "outside_syllabus": {"type": "boolean"},
                                "review_note": {"type": "string"},
                            },
                            "required": ["text", "options", "answer", "difficulty", "topic", "source_ids",
                                         "outside_syllabus", "review_note"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["type", "questions"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "instructions", "coverage_plan", "sections"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You write exam practice worksheets for a school. Every worksheet is built only from the \
approved study material you are given, which the school uploaded for this class and subject.

How to work:
- Schools set their own syllabus for each exam. When the brief includes an <exam_syllabus>, that is the \
school's official portion for this exam and the scope boundary: plan coverage across the chapters and topics \
it lists, and do not test anything it leaves out, even if a passage happens to mention it.
- Otherwise, read the syllabus passages to find the topics in scope. Either way, spread the questions \
across the in-scope topics rather than clustering on one chapter.
- Ground every question in the passages. List the passage ids (like "C12") that support the question and its \
answer in source_ids. A student who studied only these passages must be able to answer it.
- If a question needs a concept that the syllabus passages do not include, set outside_syllabus to true and \
explain in review_note; otherwise leave review_note empty. It is better to flag than to silently go beyond scope.
- Produce exactly the number of questions requested for each section type, and match the difficulty mix as \
closely as the counts allow.
- MCQ questions have exactly four options, one correct; the answer repeats the correct option text exactly. \
Other question types have an empty options list.
- Answers are concise model answers a teacher can mark against (for long answers, the key points).
- Lay answers out so a student can follow them, using line breaks (\\n) inside the answer string:
  • Numerical problems: one step per line: "Given: …", then "Formula: …", then each calculation on its own \
line, and a last line "Answer: <value with unit>". Never chain several equations on one line with commas.
  • Answers with several points (definitions, reasons, differences): one numbered point per line ("1. …").
  • Short factual answers: one or two plain sentences, no line breaks needed.
  • In Hindi use the same layout with "दिया गया है:", "सूत्र:" and "उत्तर:".
- Multi-part questions put each part on its own line: "(a) …", "(b) …".
- Write clear, unambiguous questions suited to the class level. Do not repeat or trivially rephrase a question.
- Write everything (title, instructions, questions, answers) in the requested language.
- The title follows this form: "<Subject> Practice Sheet – Class <n> – Exam <day> <Month>"."""


class LLMError(Exception):
    """Generation failed in a way worth retrying (network, overload, refusal, truncation)."""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=3, timeout=600.0)


def _request_kwargs() -> dict:
    s = get_settings()
    kw: dict = {}
    if s.llm_server_fallbacks and s.llm_model in ("claude-opus-5", "claude-fable-5-1"):
        kw["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
        kw["extra_body"] = {"fallbacks": "default"}
    return kw


def _final_text(message) -> str:
    """Text of the final answer. If a fallback happened mid-response, only text after the switch counts."""
    blocks = list(message.content)
    last_fallback = max((i for i, b in enumerate(blocks) if getattr(b, "type", "") == "fallback"), default=-1)
    return "".join(b.text for b in blocks[last_fallback + 1:] if getattr(b, "type", "") == "text")


def _worksheet_params(passages_block: str, brief: str, max_tokens: int) -> dict:
    s = get_settings()
    return {
        "model": s.llm_model,
        "max_tokens": max_tokens,
        # The instructions and the textbook passages form a stable prefix: cached, a regeneration of the same
        # worksheet reads them at a tenth of the price.
        "system": [{"type": "text", "text": SYSTEM_PROMPT}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": s.llm_effort, "format": {"type": "json_schema", "schema": WORKSHEET_SCHEMA}},
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": passages_block, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": brief},
        ]}],
    }


def _parse_worksheet(message) -> dict:
    if message.stop_reason == "refusal":
        cat = getattr(getattr(message, "stop_details", None), "category", None)
        raise LLMError(f"The model declined this request (category: {cat or 'unspecified'}).")
    if message.stop_reason == "max_tokens":
        raise LLMError("The worksheet was cut off at the output limit.")
    try:
        return json.loads(_final_text(message))
    except json.JSONDecodeError as e:
        raise LLMError("The model returned malformed JSON.") from e


def _gemini():
    """The Gemini implementation of these same functions, when LLM_PROVIDER=gemini."""
    if get_settings().llm_provider == "gemini":
        from . import llm_gemini
        return llm_gemini
    return None


def generate_worksheet_json(passages_block: str, brief: str) -> tuple[dict, str]:
    """Direct (interactive) call. Returns (worksheet dict, model that served it)."""
    if g := _gemini():
        return g.generate_worksheet_json(passages_block, brief)
    try:
        with _client().messages.stream(**_worksheet_params(passages_block, brief, 64000), **_request_kwargs()) as stream:
            message = stream.get_final_message()
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        raise LLMError(f"Model service unavailable: {e}") from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500 or e.status_code == 529:
            raise LLMError(f"Model service error {e.status_code}") from e
        raise  # 4xx: configuration problem, not worth retrying
    return _parse_worksheet(message), message.model


def submit_worksheet_batch(custom_id: str, passages_block: str, brief: str) -> str:
    """Queue a worksheet on the Message Batches API (50% cheaper). Returns the batch id."""
    if g := _gemini():
        return g.submit_worksheet_batch(custom_id, passages_block, brief)
    try:
        batch = _client().messages.batches.create(requests=[
            {"custom_id": custom_id, "params": _worksheet_params(passages_block, brief, 32000)},
        ])
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        raise LLMError(f"Model service unavailable: {e}") from e
    return batch.id


def poll_worksheet_batch(batch_id: str) -> tuple[dict, str] | None:
    """None while the batch is still running; otherwise (worksheet dict, model). Raises LLMError on failure."""
    if g := _gemini():
        return g.poll_worksheet_batch(batch_id)
    client = _client()
    try:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            return None
        for result in client.messages.batches.results(batch_id):
            if result.result.type == "succeeded":
                msg = result.result.message
                return _parse_worksheet(msg), msg.model
            if result.result.type == "errored":
                raise LLMError(f"The batch request failed: {result.result.error.type}")
            raise LLMError(f"The batch request was {result.result.type}.")
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
        raise LLMError(f"Model service unavailable: {e}") from e
    raise LLMError("The batch returned no result.")


def cancel_batch(batch_id: str) -> None:
    if g := _gemini():
        return g.cancel_batch(batch_id)
    try:
        _client().messages.batches.cancel(batch_id)
    except anthropic.APIError as e:
        log.info("Could not cancel batch %s: %s", batch_id, e)


def transcribe_pdf(data: bytes) -> str:
    """OCR for scanned PDFs (no text layer). Returns '' when unavailable; never raises."""
    if g := _gemini():
        return g.transcribe_pdf(data)
    s = get_settings()
    if s.llm_provider != "anthropic" or len(data) > 30 * 1024 * 1024:
        return ""
    try:
        with _client().messages.stream(
            model=s.llm_model,
            max_tokens=64000,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.standard_b64encode(data).decode()}},
                {"type": "text", "text": "Transcribe the full text of this document in reading order. Keep headings "
                                         "and numbered lists on their own lines. Output only the transcription."},
            ]}],
            **_request_kwargs(),
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason == "refusal":
            return ""
        return _final_text(message)
    except anthropic.APIError as e:
        log.warning("PDF transcription failed: %s", e)
        return ""
