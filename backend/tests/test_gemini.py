"""Gemini provider: routing, backup models on overload, skipping retired models, safety/truncation handling and
the batch flow. The Gemini API is simulated; no network calls."""
import json
from types import SimpleNamespace

import pytest
from google.genai import errors

from app import config
from app.agents import llm, llm_gemini

WORKSHEET = {"title": "T", "instructions": "I", "coverage_plan": [], "sections": [
    {"type": "mcq", "questions": [{"text": "Q?", "options": ["a", "b", "c", "d"], "answer": "a", "difficulty": "easy",
                                   "topic": "t", "source_ids": ["C1"], "outside_syllabus": False, "review_note": ""}]}]}


def _response(text=json.dumps(WORKSHEET), finish="STOP", block=None, model="gemini-test"):
    return SimpleNamespace(text=text, model_version=model, prompt_feedback=SimpleNamespace(block_reason=block),
                           candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name=finish))])


class FakeClient:
    def __init__(self, behaviour):
        self.behaviour, self.calls, self.configs = behaviour, [], []
        outer = self

        class Models:
            def generate_content(self, model, contents, config):
                outer.calls.append(model)
                outer.configs.append(config)
                b = outer.behaviour.get(model, "ok")
                if isinstance(b, Exception):
                    raise b
                return b if not isinstance(b, str) else _response(model=model)

        class Batches:
            jobs = {}

            def create(self, model, src, config):
                outer.calls.append(("batch", model))
                return SimpleNamespace(name="batches/123")

            def get(self, name):
                return outer.behaviour["batch_state"]

            def cancel(self, name):
                outer.calls.append(("cancel", name))

        self.models, self.batches = Models(), Batches()


@pytest.fixture
def gemini(monkeypatch):
    s = config.get_settings()
    monkeypatch.setattr(s, "llm_provider", "gemini")
    monkeypatch.setattr(s, "gemini_api_key", "test-key")
    monkeypatch.setattr(s, "gemini_model", "gm-main")
    monkeypatch.setattr(s, "gemini_fallback_models", "gm-backup1,gm-backup2")
    monkeypatch.setattr(s, "gemini_retry_rounds", 2)
    monkeypatch.setattr(llm_gemini.time, "sleep", lambda s: None)  # no real waiting in tests

    def install(behaviour):
        fake = FakeClient(behaviour)
        monkeypatch.setattr(llm_gemini, "_client", lambda: fake)
        return fake
    return install


def test_routes_to_gemini_with_json_schema(gemini):
    fake = gemini({})
    content, model = llm.generate_worksheet_json("<approved_material/>", "brief")
    assert content == WORKSHEET and model == "gm-main"
    cfg = fake.configs[0]
    assert cfg["response_mime_type"] == "application/json" and cfg["response_json_schema"] == llm.WORKSHEET_SCHEMA
    assert cfg["system_instruction"] == llm.SYSTEM_PROMPT


def test_backup_models_on_overload_and_retired_models_are_skipped(gemini):
    fake = gemini({"gm-main": errors.ServerError(503, {"error": {"message": "high demand"}}),
                   "gm-backup1": errors.ClientError(404, {"error": {"message": "no longer available"}})})
    _, model = llm.generate_worksheet_json("m", "b")
    assert fake.calls == ["gm-main", "gm-backup1", "gm-backup2"] and model == "gm-backup2"


def test_all_models_overloaded_waits_a_round_then_is_retryable(gemini):
    busy = errors.ServerError(503, {"error": {"message": "busy"}})
    fake = gemini({"gm-main": busy, "gm-backup1": busy, "gm-backup2": busy})
    with pytest.raises(llm.LLMError):  # LLMError → the job is retried later
        llm.generate_worksheet_json("m", "b")
    assert len(fake.calls) == 6  # two full rounds over the three models


def test_second_round_succeeds_when_demand_drops(gemini):
    busy = errors.ServerError(503, {"error": {"message": "busy"}})
    fake = gemini({"gm-main": busy, "gm-backup1": busy, "gm-backup2": busy})
    original = fake.models.generate_content

    def recover(model, contents, config):
        if len(fake.calls) >= 3:  # the spike passes before round two
            fake.behaviour.clear()
        return original(model, contents, config)
    fake.models.generate_content = recover
    _, model = llm.generate_worksheet_json("m", "b")
    assert model == "gm-main" and fake.calls[3] == "gm-main"


def test_bad_request_is_not_retried(gemini):
    gemini({"gm-main": errors.ClientError(400, {"error": {"message": "invalid schema"}})})
    with pytest.raises(RuntimeError) as e:
        llm.generate_worksheet_json("m", "b")
    assert not isinstance(e.value, llm.LLMError)


@pytest.mark.parametrize("resp", [_response(block="SAFETY"), _response(finish="MAX_TOKENS"), _response(text="not json")])
def test_blocked_truncated_or_malformed_output_is_an_error(gemini, resp):
    gemini({"gm-main": resp})
    with pytest.raises(llm.LLMError):
        llm.generate_worksheet_json("m", "b")


def test_batch_flow(gemini):
    running = SimpleNamespace(state=SimpleNamespace(name="JOB_STATE_RUNNING"), dest=None)
    fake = gemini({"batch_state": running})
    assert llm.submit_worksheet_batch("job-1", "m", "b") == "batches/123"
    assert llm.poll_worksheet_batch("batches/123") is None
    fake.behaviour["batch_state"] = SimpleNamespace(state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"), dest=SimpleNamespace(
        inlined_responses=[SimpleNamespace(error=None, response=_response(model="gm-main"))]))
    content, model = llm.poll_worksheet_batch("batches/123")
    assert content == WORKSHEET and model == "gm-main"
    fake.behaviour["batch_state"] = SimpleNamespace(state=SimpleNamespace(name="JOB_STATE_FAILED"), dest=None)
    with pytest.raises(llm.LLMError):
        llm.poll_worksheet_batch("batches/123")
    llm.cancel_batch("batches/123")
    assert ("cancel", "batches/123") in fake.calls
