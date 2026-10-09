"""Minimal LLM client for the optional AI tools (summarize, translate, ask a document).

Two providers, chosen with ``TOOLBOX_LLM_PROVIDER``:
  openai   any OpenAI-compatible chat API: OpenAI, Ollama, LM Studio, vLLM, OpenRouter...
  bedrock  AWS Bedrock via the Converse API (uses the normal AWS credential chain)

Document text is sent to whatever provider you configure. With a local server (Ollama) it never
leaves the machine; with a hosted one it does. Nothing is sent unless a provider is configured.
"""

from __future__ import annotations

import importlib.util
import re
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.core.errors import ToolError

REQUEST_TIMEOUT = 180.0
PROVIDERS = ("openai", "bedrock")


class LLM(Protocol):
    def complete(self, system: str, user: str, *, max_tokens: int = 2048) -> str: ...


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def unmet(settings: Settings | None = None) -> list[str]:
    """What is missing for the AI tools to work (empty list = ready)."""
    s = settings or get_settings()
    if s.llm_provider not in PROVIDERS:
        return ["config:TOOLBOX_LLM_PROVIDER (openai|bedrock)"]
    if not s.llm_model:
        return ["config:TOOLBOX_LLM_MODEL"]
    if s.llm_provider == "bedrock" and not _has_module("boto3"):
        return ["python:boto3"]
    return []


class OpenAICompatible:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def complete(self, system: str, user: str, *, max_tokens: int = 2048) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            r = httpx.post(self.url, json=payload, headers=self.headers, timeout=REQUEST_TIMEOUT)
        except httpx.HTTPError as e:
            raise ToolError(f"Could not reach the AI provider: {type(e).__name__}.") from None
        if r.status_code != 200:
            raise ToolError(f"The AI provider returned an error ({r.status_code}): {_reason(r)}")
        try:
            return r.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, ValueError):
            raise ToolError("The AI provider sent an answer in an unexpected format.") from None


def _reason(r: httpx.Response) -> str:
    try:
        err = r.json().get("error", {})
        text = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        text = r.text
    return re.sub(r"\s+", " ", (text or "no details"))[:200]


class Bedrock:
    def __init__(self, region: str, model: str):
        import boto3  # optional dependency

        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model = model

    def complete(self, system: str, user: str, *, max_tokens: int = 2048) -> str:
        try:
            resp = self.client.converse(
                modelId=self.model,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
            )
            blocks = resp["output"]["message"]["content"]
            return "".join(b.get("text", "") for b in blocks).strip()
        except (KeyError, TypeError):
            raise ToolError("Bedrock sent an answer in an unexpected format.") from None
        except Exception as e:  # botocore errors: credentials, access, throttling...
            raise ToolError(f"Bedrock request failed: {type(e).__name__}: {str(e)[:200]}") from None


def get_llm(settings: Settings | None = None) -> LLM:
    s = settings or get_settings()
    problems = unmet(s)
    if problems:
        raise ToolError(f"The AI provider is not configured ({', '.join(problems)}).")
    if s.llm_provider == "bedrock":
        return Bedrock(s.llm_region, s.llm_model)
    return OpenAICompatible(s.llm_base_url, s.llm_api_key, s.llm_model)
