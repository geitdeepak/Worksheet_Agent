"""Google Gemini provider for the Worksheet Creation Agent (LLM_PROVIDER=gemini).

Same contract as the Claude functions in llm.py: the same system prompt, the same worksheet JSON schema
(enforced with Gemini's JSON-schema output), direct calls for manual worksheets, the Batch API for
scheduled ones, and PDF reading for scanned or old-font Hindi books. Everything after generation —
syllabus scope, validation, PDF, delivery — is shared and provider-independent."""
import json
import logging
import time
from functools import lru_cache

from google import genai
from google.genai import errors, types

from ..config import get_settings
from .llm import SYSTEM_PROMPT, WORKSHEET_SCHEMA, LLMError

log = logging.getLogger("psa.llm.gemini")

# LLM_EFFORT → Gemini thinking level (more thinking = better questions, more cost).
_THINKING = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "HIGH", "max": "HIGH"}
_OK_STATES = {"JOB_STATE_SUCCEEDED"}
_DONE_BAD = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


@lru_cache(maxsize=2)
def _client_for(key: str) -> genai.Client:
    # One long-lived client: the SDK closes its HTTP connection when a Client object is garbage-collected,
    # so a throwaway client per call fails with "the client has been closed".
    return genai.Client(api_key=key)


def _client() -> genai.Client:
    key = get_settings().gemini_api_key
    if not key:
        raise LLMError("GEMINI_API_KEY is not set in backend/.env.")
    return _client_for(key)


def _config(max_tokens: int) -> dict:
    s = get_settings()
    cfg: dict = {
        "system_instruction": SYSTEM_PROMPT,
        "response_mime_type": "application/json",
        "response_json_schema": WORKSHEET_SCHEMA,
        "max_output_tokens": max_tokens,
        "automatic_function_calling": {"disable": True},  # no tools are used
    }
    level = _THINKING.get(s.llm_effort)
    if level:
        cfg["thinking_config"] = {"thinking_level": level}
    return cfg


def _contents(passages_block: str, brief: str) -> list[dict]:
    return [{"role": "user", "parts": [{"text": passages_block}, {"text": brief}]}]


def _wrap(e: errors.APIError) -> Exception:
    """Server problems and rate limits are worth retrying; other 4xx errors are configuration problems."""
    code = getattr(e, "code", None) or 0
    if isinstance(e, errors.ServerError) or code in (408, 429) or code >= 500:
        return LLMError(f"Gemini is unavailable right now ({code}): {getattr(e, 'message', e)}")
    return RuntimeError(f"Gemini rejected the request ({code}): {getattr(e, 'message', e)}")


def _parse(response) -> dict:
    fb = getattr(response, "prompt_feedback", None)
    if fb is not None and getattr(fb, "block_reason", None):
        raise LLMError(f"Gemini declined this request ({fb.block_reason}).")
    cand = (response.candidates or [None])[0]
    reason = getattr(getattr(cand, "finish_reason", None), "name", "") if cand else ""
    if reason == "MAX_TOKENS":
        raise LLMError("The worksheet was cut off at the output limit.")
    if reason and reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        raise LLMError(f"Gemini stopped early ({reason}).")
    text = response.text or ""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError("Gemini returned malformed JSON.") from e


def _models() -> list[str]:
    """Main model first, then the backups tried when it is overloaded (503) or rate-limited (429)."""
    s = get_settings()
    backups = [m.strip() for m in s.gemini_fallback_models.split(",") if m.strip()]
    return list(dict.fromkeys([s.gemini_model, *backups]))


def generate_worksheet_json(passages_block: str, brief: str) -> tuple[dict, str]:
    """Try the main model, then each backup. If every model is overloaded, wait and go round again
    (GEMINI_RETRY_ROUNDS) before handing back to the job's own retry schedule."""
    s = get_settings()
    last: Exception | None = None
    for round_no in range(max(1, s.gemini_retry_rounds)):
        if round_no:
            wait = s.gemini_retry_wait_seconds * round_no
            log.warning("All Gemini models busy; waiting %ss before round %s", wait, round_no + 1)
            time.sleep(wait)
        for model in _models():
            try:
                response = _client().models.generate_content(model=model, contents=_contents(passages_block, brief),
                                                             config=_config(60000))
            except errors.APIError as e:
                code = getattr(e, "code", None)
                wrapped = _wrap(e)
                # Overloaded / rate-limited, or a backup model retired for this account: try the next one now.
                if isinstance(wrapped, LLMError) or code == 404:
                    log.warning("Gemini %s unavailable (%s); trying the next model", model, code)
                    last = wrapped if isinstance(wrapped, LLMError) else (last or LLMError(f"Gemini model {model} is not available."))
                    continue
                raise wrapped from e
            return _parse(response), getattr(response, "model_version", None) or model
    raise last or LLMError("No Gemini model is configured.")


def submit_worksheet_batch(custom_id: str, passages_block: str, brief: str) -> str:
    s = get_settings()
    try:
        job = _client().batches.create(
            model=s.gemini_model,
            src=[{"contents": _contents(passages_block, brief), "config": _config(60000), "metadata": {"key": custom_id}}],
            config={"display_name": f"psa-{custom_id}"})
    except errors.APIError as e:
        raise _wrap(e) from e
    return job.name


def poll_worksheet_batch(batch_id: str) -> tuple[dict, str] | None:
    s = get_settings()
    try:
        job = _client().batches.get(name=batch_id)
    except errors.APIError as e:
        raise _wrap(e) from e
    state = getattr(job.state, "name", str(job.state))
    if state in _DONE_BAD:
        raise LLMError(f"The Gemini batch ended as {state.removeprefix('JOB_STATE_').lower()}.")
    if state not in _OK_STATES:
        return None
    responses = (job.dest.inlined_responses if job.dest else None) or []
    if not responses:
        raise LLMError("The Gemini batch returned no result.")
    first = responses[0]
    if first.error:
        raise LLMError(f"The Gemini batch request failed: {first.error}")
    return _parse(first.response), getattr(first.response, "model_version", None) or s.gemini_model


def cancel_batch(batch_id: str) -> None:
    try:
        _client().batches.cancel(name=batch_id)
    except errors.APIError as e:
        log.info("Could not cancel Gemini batch %s: %s", batch_id, e)


def transcribe_pdf(data: bytes) -> str:
    """Read a scanned or old-font PDF. Returns '' when unavailable; never raises."""
    s = get_settings()
    if len(data) > 30 * 1024 * 1024:
        return ""
    try:
        response = _client().models.generate_content(
            model=s.gemini_model,
            contents=[types.Part.from_bytes(data=data, mime_type="application/pdf"),
                      "Transcribe the full text of this document in reading order. Keep headings and numbered lists "
                      "on their own lines. Output only the transcription."],
            config={"max_output_tokens": 60000, "thinking_config": {"thinking_level": "LOW"}})
        return response.text or ""
    except (errors.APIError, LLMError, ValueError) as e:
        log.warning("Gemini PDF transcription failed: %s", e)
        return ""
