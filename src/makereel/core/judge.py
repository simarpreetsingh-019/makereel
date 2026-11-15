"""Optional AI judge: an LLM reads the shortlisted moments and scores them like an editor would.

Off by default. makereel already finds candidates with loudness, chat and hype words; the judge
only re-ranks that shortlist (a few thousand tokens per video), and writes better on-screen titles.

Providers (settings["ai"]["provider"]):
  off        no AI: picks come from signals only (default)
  local      any OpenAI-compatible local server: Ollama, LM Studio, llama.cpp... nothing leaves the machine
  claude     Anthropic's API with the user's own key (MAKEREEL_AI_KEY or ANTHROPIC_API_KEY); needs
             `pip install "makereel[ai]"`
  openai     any OpenAI-compatible cloud API with the user's own key (OpenAI, OpenRouter, Groq...)

Any failure (no server, bad key, odd reply) logs a warning and keeps the signal-only ranking.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request

from ..config import env

log = logging.getLogger(__name__)

PROVIDERS = ("off", "local", "claude", "openai")
DEFAULTS = {
    "local": {"base_url": "http://localhost:11434/v1", "model": "llama3.1:8b"},
    "claude": {"model": "claude-opus-5-5"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": ""},
}
CRITERIA = ("hook", "engagement", "value", "shareability")

SYSTEM = (
    "You are a short-form video editor choosing which moments of a long video or stream to post as "
    "vertical reels (Instagram Reels, YouTube Shorts, TikTok). For each candidate you get its transcript "
    "and the signals that flagged it (loudness spikes, chat activity, hype words). Score each from 0 to 10 on: "
    "hook (do the first seconds grab attention), engagement (reactions, tension, humour, surprise), "
    "value (is it understandable and satisfying on its own, without the rest of the video), and "
    "shareability (would people send it to a friend). Be strict: most moments are average. "
    "Also write a punchy on-screen title of at most 7 words in the speaker's language, without hashtags "
    "or emoji, and a one-sentence reason."
)

SCHEMA = {
    "type": "object",
    "properties": {"clips": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, **{c: {"type": "integer"} for c in CRITERIA},
                       "title": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["id", *CRITERIA, "title", "reason"], "additionalProperties": False}}},
    "required": ["clips"], "additionalProperties": False,
}


def _key() -> str | None:
    env()  # make sure .env has been loaded
    return os.environ.get("MAKEREEL_AI_KEY") or os.environ.get("ANTHROPIC_API_KEY") or None


def enabled(ai: dict) -> bool:
    return ai.get("provider", "off") != "off"


def _prompt(candidates: list[dict], profile: str) -> str:
    kind = "gameplay stream" if profile == "gameplay" else "podcast / talking video"
    items = "\n\n".join(
        f"<candidate id=\"{c['id']}\" seconds=\"{c['length']:.0f}\" signals=\"{', '.join(c['why']) or 'none'}\">\n"
        f"{c['text'][:1500] or '(no speech)'}\n</candidate>" for c in candidates)
    return (f"Source: a {kind}.\n\n{items}\n\nScore every candidate. Reply with JSON only: "
            '{"clips": [{"id": 0, "hook": 0, "engagement": 0, "value": 0, "shareability": 0, '
            '"title": "...", "reason": "..."}]}')


def _claude(ai: dict, prompt: str) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError('the Claude judge needs: pip install "makereel[ai]"') from e
    client = anthropic.Anthropic(api_key=_key()) if _key() else anthropic.Anthropic()
    response = client.beta.messages.create(
        model=ai.get("model") or DEFAULTS["claude"]["model"],
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",            # if the model declines, the API retries on a fallback model
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("the model declined to score these clips")
    return next((b.text for b in response.content if b.type == "text"), "")


def _openai_compatible(ai: dict, prompt: str, needs_key: bool) -> str:
    base = (ai.get("base_url") or DEFAULTS[ai["provider"]]["base_url"]).rstrip("/")
    model = ai.get("model") or DEFAULTS[ai["provider"]]["model"]
    if not model:
        raise RuntimeError("set a model name for this provider in Settings → AI judge")
    headers = {"Content-Type": "application/json"}
    if needs_key:
        if not _key():
            raise RuntimeError("set MAKEREEL_AI_KEY in .env for this provider")
        headers["Authorization"] = f"Bearer {_key()}"
    body = {"model": model, "temperature": 0.2, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    req = urllib.request.Request(f"{base}/chat/completions", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(req, timeout=180) as r:   # local models can be slow on CPU
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"]


def _parse(text: str, ids: set[int]) -> dict[int, dict]:
    start, end = text.find("{"), text.rfind("}")
    data = json.loads(text[start:end + 1])
    out = {}
    for item in data.get("clips", []):
        try:
            cid = int(item["id"])
            scores = {c: max(0, min(10, int(item[c]))) for c in CRITERIA}
        except (KeyError, TypeError, ValueError):
            continue
        if cid in ids:
            out[cid] = {**scores, "title": str(item.get("title", "")).strip()[:80],
                        "reason": str(item.get("reason", "")).strip()[:240]}
    return out


def judge(candidates: list[dict], ai: dict, profile: str) -> dict[int, dict]:
    """Scores per candidate id ({} if off or anything fails). candidates: id, text, why, length."""
    if not enabled(ai) or not candidates:
        return {}
    provider = ai["provider"]
    prompt = _prompt(candidates, profile)
    try:
        if provider == "claude":
            text = _claude(ai, prompt)
        else:
            text = _openai_compatible(ai, prompt, needs_key=provider == "openai")
        scores = _parse(text, {c["id"] for c in candidates})
    except Exception as e:  # noqa: BLE001 - the judge is optional; never fail a job over it
        log.warning("   AI judge skipped (%s): %s", provider, e)
        return {}
    log.info("   AI judge (%s) scored %d of %d moments", provider, len(scores), len(candidates))
    return scores


def blend(signal_scores: list[float], ai_scores: list[float | None], weight: float) -> list[float]:
    """Mix signal and AI scores (both normalised to 0..1). Candidates the AI skipped keep their signal score."""
    lo, hi = min(signal_scores), max(signal_scores)
    span = (hi - lo) or 1.0
    out = []
    for s, a in zip(signal_scores, ai_scores, strict=True):
        norm = (s - lo) / span
        out.append(norm if a is None else (1 - weight) * norm + weight * a)
    return out

