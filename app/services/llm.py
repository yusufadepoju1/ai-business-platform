"""Groq LLM access through LangChain with graceful failure handling."""
import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..config import settings

log = logging.getLogger(__name__)
_override = None  # tests may inject a fake LLM exposing .invoke(messages) -> obj.content


class LLMUnavailable(Exception):
    """Raised when no API key is configured or the provider call fails."""


def set_llm_override(llm) -> None:
    global _override
    _override = llm


def llm_configured() -> bool:
    return _override is not None or bool(settings.groq_api_key)


def get_llm(temperature: float = 0.2):
    if _override is not None:
        return _override
    if not settings.groq_api_key:
        raise LLMUnavailable("The AI service is not configured. Set GROQ_API_KEY on the server.")
    from langchain_groq import ChatGroq
    return ChatGroq(model=settings.groq_model, temperature=temperature, api_key=settings.groq_api_key,
                    timeout=40, max_retries=1)


def to_lc_messages(system: str, history: list[dict] | None, user: str):
    msgs: list[Any] = [SystemMessage(content=system)]
    for m in history or []:
        if m["role"] == "customer":
            msgs.append(HumanMessage(content=m["content"]))
        elif m["role"] in ("ai", "human"):
            msgs.append(AIMessage(content=m["content"]))
    msgs.append(HumanMessage(content=user))
    return msgs


def invoke_text(system: str, user: str, history: list[dict] | None = None, temperature: float = 0.2) -> str:
    llm = get_llm(temperature)
    try:
        res = llm.invoke(to_lc_messages(system, history, user))
    except LLMUnavailable:
        raise
    except Exception as exc:
        log.exception("LLM call failed")
        raise LLMUnavailable(f"The AI provider returned an error: {type(exc).__name__}") from exc
    content = getattr(res, "content", res)
    return content if isinstance(content, str) else str(content)


def extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    raise ValueError("Model did not return valid JSON")


def invoke_json(system: str, user: str, history: list[dict] | None = None, temperature: float = 0.1) -> dict:
    raw = invoke_text(system + "\n\nRespond with ONE valid JSON object only. No prose, no markdown.",
                      user, history, temperature)
    try:
        return extract_json(raw)
    except ValueError as exc:
        raise LLMUnavailable("The AI returned an unreadable response. Please try again.") from exc
