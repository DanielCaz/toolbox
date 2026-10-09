from pathlib import Path

from pydantic import BaseModel, Field

from app.core import llm
from app.core.files import safe_name
from app.core.tool import Tool, ToolContext
from app.tools.ai._common import AI_ACCEPTS, INJECTION_NOTE, AiTool, chunk_text, read_pages

TRANSLATE_CHUNK = 6000


class TranslateParams(BaseModel):
    target_language: str = Field(
        "English", min_length=2, max_length=40, description="Translate into (e.g. Spanish)"
    )
    keep_formatting: bool = Field(True, description="Keep paragraph breaks, lists and numbering")


class Translate(AiTool, Tool):
    id = "ai.translate"
    name = "Translate a document"
    category = "ai"
    description = (
        "Translate a PDF or text file into another language with the AI provider you configured. "
        "The document's text is sent to that provider. The result is a text file."
    )
    accepts = AI_ACCEPTS
    batch = True
    slow = True
    Params = TranslateParams

    def run(self, files: list[Path], params: TranslateParams, ctx: ToolContext):
        src = files[0]
        model = llm.get_llm()
        text = "\n\n".join(t for _, t in read_pages(src))
        fmt = "Keep the paragraph breaks, lists and numbering." if params.keep_formatting else ""
        system = (
            f"You are a professional translator. Translate the user's text into "
            f"{params.target_language}. {fmt} Output only the translation, with no comments. "
            f"{INJECTION_NOTE}"
        )
        chunks = chunk_text(text, TRANSLATE_CHUNK)
        parts = []
        for i, chunk in enumerate(chunks, start=1):
            ctx.check_cancelled()
            ctx.progress((i - 1) / len(chunks), f"Translating part {i} of {len(chunks)}")
            parts.append(model.complete(system, chunk, max_tokens=4096))
        tag = safe_name(params.target_language).lower().replace(" ", "-")
        out = ctx.out_unique(f"{src.stem}.{tag}.txt")
        out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
        return [out]
