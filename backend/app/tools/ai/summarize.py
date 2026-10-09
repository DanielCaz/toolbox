from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core import llm
from app.core.tool import Tool, ToolContext
from app.tools.ai._common import (
    AI_ACCEPTS,
    CHUNK_CHARS,
    INJECTION_NOTE,
    AiTool,
    chunk_text,
    read_pages,
)

LENGTHS = {
    "short": "in 3 to 5 sentences",
    "medium": "in about 150 to 250 words",
    "detailed": "thoroughly, in about 400 to 600 words, keeping the document's structure",
}


class SummarizeParams(BaseModel):
    length: Literal["short", "medium", "detailed"] = Field("medium", description="How long")
    style: Literal["paragraphs", "bullets"] = Field("bullets", description="Layout of the summary")
    language: str = Field(
        "",
        max_length=40,
        description="Write the summary in this language. Blank = same as the document",
    )


class Summarize(AiTool, Tool):
    id = "ai.summarize"
    name = "Summarize a document"
    category = "ai"
    description = (
        "Summarize a PDF or text file with the AI provider you configured. "
        "The document's text is sent to that provider."
    )
    accepts = AI_ACCEPTS
    batch = True
    slow = True
    output = "text"
    Params = SummarizeParams

    def run(self, files: list[Path], params: SummarizeParams, ctx: ToolContext) -> str:
        src = files[0]
        model = llm.get_llm()
        pages = read_pages(src)
        text = "\n\n".join(t for _, t in pages)
        lang = (
            f"Write in {params.language}."
            if params.language
            else "Write in the document's language."
        )
        layout = (
            "Use short bullet points." if params.style == "bullets" else "Use plain paragraphs."
        )
        system = (
            f"You summarize documents faithfully. {layout} {lang} Do not add facts that are not "
            f"in the text. {INJECTION_NOTE}"
        )

        chunks = chunk_text(text, CHUNK_CHARS)
        if len(chunks) == 1:
            ctx.progress(0.2, "Summarizing")
            return model.complete(
                system, f"Summarize this document {LENGTHS[params.length]}:\n\n{chunks[0]}"
            )

        partials = []
        for i, chunk in enumerate(chunks, start=1):
            ctx.check_cancelled()
            ctx.progress(0.9 * (i - 1) / len(chunks), f"Reading part {i} of {len(chunks)}")
            partials.append(
                model.complete(
                    system,
                    f"This is part {i} of {len(chunks)} of a long document. Summarize it in "
                    f"about 120 words, keeping names, numbers and decisions:\n\n{chunk}",
                    max_tokens=600,
                )
            )
        ctx.check_cancelled()
        ctx.progress(0.92, "Combining")
        joined = "\n\n".join(f"[Part {i}]\n{p}" for i, p in enumerate(partials, start=1))
        return model.complete(
            system,
            f"These are summaries of consecutive parts of one document. Combine them into one "
            f"summary {LENGTHS[params.length]}:\n\n{joined}",
        )
