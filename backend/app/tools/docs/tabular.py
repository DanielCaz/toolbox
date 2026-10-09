from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.core import tables
from app.core.errors import ToolError
from app.core.files import sniff_mime
from app.core.tool import Tool, ToolContext


class TabularParams(BaseModel):
    to: Literal["xlsx", "csv", "tsv", "json", "jsonl"] = Field("xlsx", description="Output format")
    infer_types: bool = Field(
        True,
        description="CSV input: turn 42, 3.14 and true into numbers/booleans "
        "(ids with leading zeros such as 00123 always stay text)",
    )
    excel_bom: bool = Field(
        True, description="CSV/TSV output: add a byte-order mark so Excel shows accents correctly"
    )
    sheet: str = Field(
        "",
        description="XLSX input: convert only this sheet. Blank = every sheet "
        "(CSV/TSV/JSONL then give one file per sheet; JSON gives one file keyed by sheet)",
    )


class Tabular(Tool):
    id = "docs.tabular"
    name = "Spreadsheet converter"
    category = "docs"
    description = "Convert between CSV, TSV, Excel (.xlsx), JSON and JSON Lines."
    accepts = [
        "text/*",
        "application/json",
        "application/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]
    batch = True
    Params = TabularParams

    def run(self, files: list[Path], params: TabularParams, ctx: ToolContext):
        src = files[0]
        kind = tables.detect_kind(src, sniff_mime(src))
        if kind == params.to:
            raise ToolError(f"'{src.name}' is already {params.to.upper()}.")

        book = tables.read_any(src, kind, infer_types=params.infer_types, sheet=params.sheet)
        if not any(book.values()):
            raise ToolError(f"'{src.name}' has no data.")
        ctx.progress(0.5, f"Writing {params.to.upper()}")

        stem, outputs = src.stem, []
        if params.to == "xlsx":
            out = ctx.out_unique(f"{stem}.xlsx")
            tables.write_xlsx(book, out)
            outputs.append(out)
        elif params.to == "json":
            out = ctx.out_unique(f"{stem}.json")
            tables.write_json(book, out)
            outputs.append(out)
        else:  # csv / tsv / jsonl: one file per sheet
            ext = params.to
            for name, table in book.items():
                suffix = "" if len(book) == 1 else f"-{tables.sheet_name(name, set())}"
                out = ctx.out_unique(f"{stem}{suffix}.{ext}")
                if ext == "jsonl":
                    tables.write_jsonl(table, out)
                else:
                    tables.write_delimited(table, out, tab=ext == "tsv", bom=params.excel_bom)
                outputs.append(out)
        return outputs
