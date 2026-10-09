from pathlib import Path
from typing import Literal

import pdfplumber
from pydantic import BaseModel, Field

from app.core import tables
from app.core.errors import ToolError
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf, selected_pages


class PdfTablesParams(BaseModel):
    pages: str = Field("", description="Pages to scan, e.g. 1-3,5. Empty = every page.")
    strategy: Literal["lines", "text"] = Field(
        "lines",
        description="lines: tables drawn with ruling lines or cell borders · "
        "text: tables laid out only with spacing (try this if 'lines' finds nothing)",
    )
    output: Literal["xlsx", "csv"] = Field(
        "xlsx", description="xlsx: one workbook, a sheet per table · csv: one file per table"
    )


def _clean(cell: object) -> str:
    return " ".join(str(cell).split()) if cell is not None else ""


class PdfTables(Tool):
    id = "ocr.tables"
    name = "PDF tables to Excel / CSV"
    category = "ocr"
    description = "Find the tables in a text-based PDF and export them as a spreadsheet."
    accepts = ["application/pdf"]
    batch = True
    slow = True
    Params = PdfTablesParams

    def run(self, files: list[Path], params: PdfTablesParams, ctx: ToolContext):
        src = files[0]
        total = len(open_pdf(src).pages)
        indexes = selected_pages(params.pages, total)
        settings = {"vertical_strategy": params.strategy, "horizontal_strategy": params.strategy}

        found: dict[str, tables.Table] = {}
        try:
            with pdfplumber.open(src) as pdf:
                for n, i in enumerate(indexes, start=1):
                    ctx.check_cancelled()
                    for t_no, raw in enumerate(
                        pdf.pages[i].extract_tables(table_settings=settings), start=1
                    ):
                        rows = [[_clean(c) for c in row] for row in raw]
                        rows = [r for r in rows if any(r)]
                        if len(rows) >= 1 and max(len(r) for r in rows) >= 2:
                            found[f"p{i + 1}-t{t_no}"] = rows
                    ctx.progress(n / len(indexes), f"Scanned page {i + 1}")
        except ToolError:
            raise
        except Exception:
            raise ToolError(f"'{src.name}' could not be analysed for tables.") from None

        if not found:
            hint = (
                "Try the 'text' strategy."
                if params.strategy == "lines"
                else "If the PDF is a scan, run 'OCR a PDF' first."
            )
            raise ToolError(f"No tables found. {hint}")

        if params.output == "xlsx":
            out = ctx.out_unique(f"{src.stem}-tables.xlsx")
            tables.write_xlsx(found, out)
            return [out]
        outputs = []
        for name, rows in found.items():
            out = ctx.out_unique(f"{src.stem}-{name}.csv")
            tables.write_delimited(rows, out)
            outputs.append(out)
        return outputs
