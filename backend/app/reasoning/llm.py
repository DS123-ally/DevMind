"""Optional wording pass. Bullets that are not grounded in graph facts are discarded."""

from __future__ import annotations

import json
import logging

import httpx

from app.config import Settings
from app.reasoning.facts import BriefingFacts
from app.reasoning.narrator import corpus_tokens, grounded_bullets, narrate, project_has_reasons

logger = logging.getLogger("devmind.llm")


def compose(settings: Settings, facts: BriefingFacts) -> dict:
    briefing = narrate(facts)
    if not settings.llm_enabled:
        return briefing
    try:
        rewritten = _rewrite(settings, facts)
    except Exception:
        logger.exception("Language model wording failed; keeping the graph briefing")
        return briefing
    if not rewritten:
        return briefing

    corpus = corpus_tokens(facts)
    what = grounded_bullets(rewritten.get("what") or [], corpus)
    why = grounded_bullets(rewritten.get("why") or [], corpus)
    headline = (rewritten.get("headline") or "").strip()
    if what:
        briefing["what"] = what
    if why and project_has_reasons(facts):
        briefing["why"] = why
    if headline and grounded_bullets([headline], corpus):
        briefing["headline"] = headline
    briefing["voice"] = "graph+model"
    return briefing


def _rewrite(settings: Settings, facts: BriefingFacts) -> dict | None:
    payload = {
        "model": settings.llm_model,
        "temperature": 0.1,
        "max_tokens": 900,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You write a project briefing from graph facts. "
                    "Use only the facts in the user message. "
                    "Do not invent a rationale, owner, or behavior. "
                    "If the facts do not explain why, leave why empty. "
                    "Reply with a JSON object only, keys headline, what, why. "
                    "what and why are arrays of short sentences. No markdown."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": facts.question,
                        "mode": facts.mode,
                        "summary": facts.summary,
                        "symbols": [symbol.__dict__ for symbol in facts.symbols],
                        "files": [file.__dict__ for file in facts.files],
                        "technologies": facts.technologies,
                        "decisions": [decision.__dict__ for decision in facts.decisions],
                        "issues": [issue.__dict__ for issue in facts.issues],
                        "errors": [error.__dict__ for error in facts.errors],
                        "pullRequests": [pull.__dict__ for pull in facts.pull_requests],
                        "snippets": facts.snippets[:8],
                    },
                    default=str,
                ),
            },
        ],
    }
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    if "openrouter.ai" in settings.llm_base_url:
        headers["HTTP-Referer"] = "https://github.com/DS123-ally/DevMind"
        headers["X-Title"] = "DevMind"
    timeout = 90.0 if "openrouter.ai" in settings.llm_base_url else 30.0
    response = _post_chat(settings.llm_base_url, payload, headers, timeout)
    content = _message_text(response)
    return _parse_json(content)


def _post_chat(base_url: str, payload: dict, headers: dict, timeout: float) -> httpx.Response:
    url = f"{base_url}/chat/completions"
    response = httpx.post(url, json={**payload, "response_format": {"type": "json_object"}}, headers=headers, timeout=timeout)
    if response.status_code == 400:
        logger.info("Model rejected JSON mode; retrying without response_format")
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    if response.status_code >= 400:
        logger.warning("Language model HTTP %s: %s", response.status_code, response.text[:800])
        response.raise_for_status()
    return response


def _message_text(response: httpx.Response) -> str:
    message = response.json()["choices"][0]["message"]
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        content = "".join(parts)
    text = (content or "").strip()
    if not text:
        text = str(message.get("reasoning") or "").strip()
    return text


def _parse_json(content: str) -> dict | None:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
