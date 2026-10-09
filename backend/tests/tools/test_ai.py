"""AI tools with a fake model, plus the real HTTP/Bedrock client code against stand-ins."""

import importlib.machinery
import json
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import Settings, get_settings
from app.core import llm
from app.core.errors import ToolError
from app.core.registry import Registry
from app.tools.ai._common import chunk_text, read_pages, top_passages
from app.tools.ai.ask import AskDocument
from app.tools.ai.summarize import Summarize
from app.tools.ai.translate import Translate


class FakeLLM:
    def __init__(self, reply=lambda s, u: "ANSWER"):
        self.calls, self.reply = [], reply

    def complete(self, system, user, *, max_tokens=2048):
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        return self.reply(system, user)


@pytest.fixture
def fake(monkeypatch):
    model = FakeLLM()
    monkeypatch.setattr(llm, "get_llm", lambda settings=None: model)
    return model


@pytest.fixture
def text_file(tmp_path):
    def _make(name="notes.txt", body="Quarterly revenue grew 12 percent."):
        p = tmp_path / "in" / name
        p.parent.mkdir(exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p

    return _make


# -- availability -------------------------------------------------------------
def test_unconfigured_ai_tools_report_what_is_missing():
    assert "config:TOOLBOX_LLM_PROVIDER (openai|bedrock)" in llm.unmet(Settings())
    assert llm.unmet(Settings(llm_provider="openai")) == ["config:TOOLBOX_LLM_MODEL"]
    assert llm.unmet(Settings(llm_provider="openai", llm_model="m")) == []
    with pytest.raises(ToolError, match="not configured"):
        llm.get_llm(Settings())


def test_catalog_marks_ai_tools_unavailable_until_configured(monkeypatch):
    monkeypatch.delenv("TOOLBOX_LLM_PROVIDER", raising=False)
    get_settings.cache_clear()
    reg = Registry()
    entry = reg.describe(reg.get("ai.summarize"))
    assert entry["available"] is False and entry["missing"][0].startswith("config:")

    monkeypatch.setenv("TOOLBOX_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TOOLBOX_LLM_MODEL", "gpt-test")
    get_settings.cache_clear()
    assert reg.describe(reg.get("ai.summarize"))["available"] is True
    get_settings.cache_clear()


def test_bedrock_needs_boto3(monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda n, *a, **k: None if n == "boto3" else real(n, *a, **k)
    )
    assert llm.unmet(Settings(llm_provider="bedrock", llm_model="m")) == ["python:boto3"]


# -- text helpers -------------------------------------------------------------
def test_chunk_text_respects_size_and_keeps_everything():
    text = "\n\n".join(f"paragraph {i} " + "word " * 40 for i in range(50))
    chunks = chunk_text(text, 1000)
    assert all(len(c) <= 1000 for c in chunks) and len(chunks) > 5
    assert "".join(c.replace("\n\n", "") for c in chunks).count("paragraph") == 50
    assert [len(c) for c in chunk_text("x" * 2500, 1000)] == [1000, 1000, 500]  # one huge paragraph
    assert chunk_text("") == []


def test_top_passages_finds_the_relevant_page():
    filler = "lorem ipsum dolor sit amet " * 30
    pages = [(i, filler) for i in range(1, 9)]
    pages[4] = (5, filler + " The warranty period is 24 months from delivery. " + filler)
    got = top_passages(pages, "How long is the warranty period?", limit=2)
    assert 5 in [n for n, _ in got]
    assert [n for n, _ in got] == sorted(n for n, _ in got)  # document order


def test_read_pages_errors(tmp_path, text_file):
    from pypdf import PdfWriter

    blank_pdf = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    with blank_pdf.open("wb") as fh:
        writer.write(fh)
    with pytest.raises(ToolError, match="no text"):
        read_pages(text_file("empty.txt", "   "))
    with pytest.raises(ToolError, match="no text"):
        read_pages(blank_pdf)  # pages without text, like a scan
    big = text_file("big.txt", "a" * 600_001)
    with pytest.raises(ToolError, match="too long"):
        read_pages(big)


# -- tools --------------------------------------------------------------------
def test_summarize_single_call(run_tool, fake, text_file):
    fake.reply = lambda s, u: "- Revenue +12%"
    out = run_tool(Summarize, [text_file()], length="short", style="bullets", language="Spanish")
    assert out == "- Revenue +12%"
    [call] = fake.calls
    assert "Quarterly revenue grew" in call["user"]
    assert "Write in Spanish" in call["system"] and "bullet" in call["system"]
    assert "untrusted" in call["system"]  # injection note present


def test_summarize_long_document_is_map_reduced(run_tool, fake, text_file):
    body = "\n\n".join(f"Section {i}. " + "detail " * 400 for i in range(20))  # ~60k chars
    fake.reply = lambda s, u: f"summary#{len(fake.calls)}"
    out = run_tool(Summarize, [text_file("long.txt", body)])
    assert len(fake.calls) > 3
    final = fake.calls[-1]
    assert "[Part 1]" in final["user"] and "summary#1" in final["user"]
    assert out == f"summary#{len(fake.calls)}"


def test_translate_writes_a_text_file(run_tool, fake, text_file):
    fake.reply = lambda s, u: "Los ingresos crecieron un 12 por ciento."
    [out] = run_tool(Translate, [text_file()], target_language="Spanish")
    assert out.name == "notes.spanish.txt"
    assert out.read_text().strip() == "Los ingresos crecieron un 12 por ciento."
    assert "into Spanish" in fake.calls[0]["system"]


def test_ask_small_document_sends_everything(run_tool, fake, text_file):
    run_tool(AskDocument, [text_file()], question="How much did revenue grow?")
    [call] = fake.calls
    assert "[Page 1]" in call["user"] and "grew 12 percent" in call["user"]
    assert "Question: How much did revenue grow?" in call["user"]


def test_ask_large_document_sends_only_relevant_excerpts(run_tool, fake, text_file):
    filler = "\n\n".join("lorem ipsum dolor sit amet " * 20 for _ in range(400))  # ~210k chars
    body = filler + "\n\nThe warranty period is 24 months from delivery.\n\n" + filler
    run_tool(AskDocument, [text_file("big.txt", body)], question="How long is the warranty period?")
    [call] = fake.calls
    assert "warranty period is 24 months" in call["user"]
    assert len(call["user"]) < 30_000
    assert "excerpts" in call["user"]


def test_ask_pdf_cites_pages(run_tool, fake, make_pdf):
    run_tool(AskDocument, [make_pdf("doc.pdf", 3)], question="What is on page 2?")
    assert "[Page 2]" in fake.calls[0]["user"]


def test_model_errors_surface_cleanly(run_tool, monkeypatch, text_file):
    class Broken:
        def complete(self, *a, **k):
            raise ToolError("The AI provider returned an error (429): rate limited")

    monkeypatch.setattr(llm, "get_llm", lambda settings=None: Broken())
    with pytest.raises(ToolError, match="429"):
        run_tool(Summarize, [text_file()])


# -- OpenAI-compatible client against a real local HTTP server -----------------
@pytest.fixture
def api_server():
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        mode = "ok"

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.update(path=self.path, auth=self.headers.get("Authorization"), body=body)
            if Handler.mode == "ok":
                payload, code = {"choices": [{"message": {"content": " hello back "}}]}, 200
            elif Handler.mode == "limit":
                payload, code = {"error": {"message": "Rate\nlimit  hit"}}, 429
            else:
                payload, code = {"unexpected": True}, 200
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1", seen, Handler
    server.shutdown()


def test_openai_client_request_and_response(api_server):
    base, seen, handler = api_server
    client = llm.OpenAICompatible(base, "sk-test", "my-model")
    assert client.complete("be brief", "hi", max_tokens=50) == "hello back"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "my-model" and seen["body"]["max_tokens"] == 50
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]

    assert llm.OpenAICompatible(base, "", "m").complete("s", "u")  # local servers: no key
    assert seen["auth"] is None

    handler.mode = "limit"
    with pytest.raises(ToolError, match=r"\(429\): Rate limit hit"):
        client.complete("s", "u")
    handler.mode = "weird"
    with pytest.raises(ToolError, match="unexpected format"):
        client.complete("s", "u")
    handler.mode = "ok"


def test_openai_client_unreachable_server_is_a_clean_error():
    with pytest.raises(ToolError, match="Could not reach"):
        llm.OpenAICompatible("http://127.0.0.1:1/v1", "", "m").complete("s", "u")


def test_get_llm_builds_the_configured_provider(monkeypatch):
    s = Settings(llm_provider="openai", llm_model="m", llm_base_url="http://x/v1/", llm_api_key="k")
    client = llm.get_llm(s)
    assert isinstance(client, llm.OpenAICompatible) and client.url == "http://x/v1/chat/completions"


def test_bedrock_client_uses_converse(monkeypatch):
    calls = {}

    class FakeClient:
        def converse(self, **kw):
            calls.update(kw)
            return {"output": {"message": {"content": [{"text": "Hi "}, {"text": "there"}]}}}

    boto = types.ModuleType("boto3")
    boto.__spec__ = importlib.machinery.ModuleSpec("boto3", None)  # so find_spec() sees it
    boto.client = lambda service, region_name=None: (
        calls.update(service=service, region=region_name) or FakeClient()
    )
    monkeypatch.setitem(sys.modules, "boto3", boto)
    s = Settings(llm_provider="bedrock", llm_model="eu.anthropic.test-v1", llm_region="eu-west-1")
    assert llm.get_llm(s).complete("sys", "user", max_tokens=99) == "Hi there"
    assert calls["service"] == "bedrock-runtime" and calls["region"] == "eu-west-1"
    assert calls["modelId"] == "eu.anthropic.test-v1"
    assert calls["system"] == [{"text": "sys"}]
    assert calls["inferenceConfig"]["maxTokens"] == 99


def test_bedrock_failures_are_user_facing(monkeypatch):
    class Boom:
        def converse(self, **kw):
            raise RuntimeError("AccessDeniedException: no access to model")

    boto = types.ModuleType("boto3")
    boto.client = lambda *a, **k: Boom()
    monkeypatch.setitem(sys.modules, "boto3", boto)
    client = llm.Bedrock("us-east-1", "m")
    with pytest.raises(ToolError, match="Bedrock request failed: RuntimeError: AccessDenied"):
        client.complete("s", "u")
