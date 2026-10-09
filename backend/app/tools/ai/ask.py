from pathlib import Path

from pydantic import BaseModel, Field

from app.core import llm
from app.core.tool import Tool, ToolContext
from app.tools.ai._common import AI_ACCEPTS, INJECTION_NOTE, AiTool, read_pages, top_passages

WHOLE_DOC_CHARS = 60_000  # up to this size the entire document is sent


class AskParams(BaseModel):
    question: str = Field(min_length=3, max_length=1000, description="What do you want to know?")


class AskDocument(AiTool, Tool):
    id = "ai.ask"
    name = "Ask a document"
    category = "ai"
    description = (
        "Ask a question about a PDF or text file and get an answer with page references, using "
        "the AI provider you configured. Relevant passages of the document are sent to it."
    )
    accepts = AI_ACCEPTS
    batch = True
    slow = True
    output = "text"
    Params = AskParams

    def run(self, files: list[Path], params: AskParams, ctx: ToolContext) -> str:
        src = files[0]
        model = llm.get_llm()
        pages = read_pages(src)
        total = sum(len(t) for _, t in pages)
        if total <= WHOLE_DOC_CHARS:
            passages = [(n, t) for n, t in pages if t]
            scope = "the whole document"
        else:
            ctx.progress(0.2, "Finding the relevant passages")
            passages = top_passages(pages, params.question)
            scope = "the most relevant excerpts of a long document"
        context = "\n\n".join(f"[Page {n}]\n{t}" for n, t in passages)
        system = (
            "You answer questions using only the document excerpts provided. Cite page numbers "
            "like (p. 3). If the answer is not in the excerpts, say so plainly instead of "
            f"guessing. {INJECTION_NOTE}"
        )
        ctx.progress(0.5, "Asking")
        return model.complete(
            system, f"Here is {scope}:\n\n{context}\n\nQuestion: {params.question}"
        )
