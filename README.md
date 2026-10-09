# Toolbox

A self-hosted toolbox of everyday file utilities: PDF, images, OCR, documents, audio and video, archives,
QR codes, plus text and developer helpers that run in the browser. Chain tools into **pipelines**, drop files
into a **watch folder**, or use the optional **AI tools**. One Docker image, one port, one CLI. Files stay on
your machine unless you choose to configure an AI provider (see [AI tools](#ai-tools-optional)).

This implements phases 0 to 6 of the implementation plan.

## Tools

37 server tools plus the in-browser ones. A tool whose binary or package is missing shows as unavailable
instead of crashing the app; `/api/health` lists what is missing.

| Category | Tool ids |
| --- | --- |
| PDF | `pdf.merge` `pdf.split` `pdf.rotate` `pdf.compress` `pdf.extract_pages` `pdf.to_images` `pdf.extract_text` `pdf.watermark` `pdf.page_numbers` `pdf.protect` `pdf.unlock` `pdf.strip_metadata` |
| Images | `image.convert` (incl. HEIC) `image.resize` `image.compress` `image.crop_rotate` `image.strip_exif` `image.to_pdf` `image.favicon` · optional `image.remove_bg` |
| OCR | `ocr.pdf` (scan to searchable PDF) `ocr.image` `ocr.tables` (PDF tables to spreadsheet) |
| Documents | `docs.office_to_pdf` (LibreOffice) `docs.markdown` (Pandoc: md/html/docx/odt/epub/rst/latex/pdf) `docs.tabular` (csv/tsv/xlsx/json/jsonl) |
| Files | `files.archive` (create/extract zip, tar.gz, 7z) |
| QR | `qr.read` (QR codes and barcodes from images) |
| Audio & video | `media.convert` `media.extract_audio` `media.trim` `media.compress_video` `media.to_gif` · optional `media.transcribe` (Whisper) |
| AI | `ai.summarize` `ai.translate` `ai.ask` (need a provider, see below) |
| In the browser | Base64, URL encode, JSON/YAML, regex tester, diff, case converter, line tools, text stats, HTML entities, UUID, password generator, hashes, JWT decode, timestamps, cron explainer, color converter, URL parts, QR generator |

Most single-file tools are **batch** tools: give them ten files and you get ten results.
Every run is a **job** with progress, and server jobs can be **cancelled** (running ffmpeg, Ghostscript,
LibreOffice and similar processes are killed).

## Run it

### Docker (recommended)

```bash
docker compose up -d --build
# open http://localhost:8080
```

- `FLAVOR=full` (default) includes LibreOffice, Pandoc and ffmpeg. `FLAVOR=slim` leaves them out for a much
  smaller image; the tools that need them show as unavailable. Set it under `build.args` in `docker-compose.yml`.
- `EXTRAS` adds optional Python packages, e.g. `"--extra bedrock --extra transcribe --extra remove-bg"`.
- The port is bound to `127.0.0.1`. Change it to `"8080:8080"` for LAN access (there is no auth, so only do
  that on a network you trust).
- Job files live in `./data/jobs` and are deleted after `TOOLBOX_JOB_TTL_MIN` minutes (default 60).

> The Docker image has **not been built or run** by the author of this code (no Docker daemon was available
> while it was written). The backend, CLI and built frontend were tested outside Docker with the same
> binaries (ffmpeg, LibreOffice, Pandoc, Tesseract, Ghostscript). Expect to fix a package name or two on the
> first `docker compose build`, and please tell me what breaks.

### Local development

You need Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, and the binaries you want to use:

```bash
# macOS:  brew install tesseract ghostscript qpdf libmagic pandoc ffmpeg ; brew install --cask libreoffice
# Debian: sudo apt install tesseract-ocr ghostscript qpdf unpaper pngquant libmagic1 \
#                          libreoffice-writer libreoffice-calc libreoffice-impress pandoc ffmpeg

make dev-api     # terminal 1: FastAPI with autoreload on :8080
make dev-web     # terminal 2: Vite on :5173, proxies /api to :8080
make test        # backend tests
cd frontend && npm test
```

To serve the built UI from FastAPI without Docker:
`cd frontend && npm ci && npm run build && cp -r dist ../backend/static`, then `make dev-api`.

The UI is an installable app (PWA) and its shell opens offline, where the in-browser tools keep working.
Server tools always need the server.

## Pipelines

Chain tools so each step's output feeds the next: split a PDF, number its pages, compress it. Build them on
the **Pipelines** page, save them as presets, and run them on files. A tool that produces text (like
`pdf.extract_text`) can only be the last step. If a step cannot accept the previous output, the job fails with
a message naming the step.

Saved pipelines are JSON files in `data/pipelines/<id>.json`, so you can keep them in git or share them:

```json
{
  "name": "Scan to searchable PDF",
  "description": "",
  "steps": [
    { "tool": "ocr.pdf", "params": { "languages": "eng+spa" } },
    { "tool": "pdf.compress", "params": {} }
  ]
}
```

```bash
uv run python cli.py pipeline scan-to-searchable-pdf scan.pdf -o out/     # saved id
uv run python cli.py pipeline ./my-pipeline.json a.pdf b.pdf -o out/      # or a file
```

## Watch folder

Set `TOOLBOX_WATCH_DIR` (the Docker compose file maps `./inbox` to `/inbox`). Make a folder named after a
saved pipeline's id and drop files into it:

```
inbox/scan-to-searchable-pdf/        drop files here
inbox/scan-to-searchable-pdf/_out/   results
inbox/scan-to-searchable-pdf/_done/  originals that were processed
inbox/scan-to-searchable-pdf/_failed/ originals that failed, each with <name>.error.txt
```

Files are picked up once their size has stopped changing between scans (`TOOLBOX_WATCH_INTERVAL`, default
2 s), so half-copied files are left alone. Symlinks, hidden files, and `.part`/`.tmp`/`.crdownload` files are
ignored. Without the server: `uv run python cli.py watch ./inbox`.

## AI tools (optional)

`ai.summarize`, `ai.translate` and `ai.ask` are off until you configure a provider. **They send the
document's text (for `ai.ask`, the relevant passages) to that provider.** With a local model server such as
Ollama nothing leaves your machine; with a hosted provider it does.

| Provider | Settings |
| --- | --- |
| Local / any OpenAI-compatible API (Ollama, LM Studio, vLLM, OpenAI, OpenRouter) | `TOOLBOX_LLM_PROVIDER=openai`, `TOOLBOX_LLM_MODEL=...`, `TOOLBOX_LLM_BASE_URL=http://host.docker.internal:11434/v1`, `TOOLBOX_LLM_API_KEY=...` (blank is fine locally) |
| AWS Bedrock | `TOOLBOX_LLM_PROVIDER=bedrock`, `TOOLBOX_LLM_MODEL=<model or inference-profile id>`, `TOOLBOX_LLM_REGION=us-east-1`, AWS credentials in the environment, and `--extra bedrock` |

Long documents are summarized in parts; `ai.ask` sends the whole document up to about 60,000 characters and
only the best-matching excerpts beyond that (keyword ranking, no embeddings). Documents over 600,000
characters are refused. Scanned PDFs need `ocr.pdf` first. Document text is treated as untrusted data in the
prompts, and these tools cannot call other tools or touch files, so the worst a hostile document can do is
produce a wrong answer.

## Optional local AI models

`media.transcribe` (faster-whisper) and `image.remove_bg` (rembg) are heavy, so they are separate extras:
`uv sync --extra transcribe --extra remove-bg`. They download their model on first use into
`TOOLBOX_MODEL_DIR` (default `data/models`); that first download needs internet access.

## CLI

```bash
cd backend
uv run python cli.py list
uv run python cli.py info pdf.split
uv run python cli.py run pdf.merge a.pdf b.pdf -p output_name=both.pdf -o out/
uv run python cli.py run media.convert talk.mov -p to=mp4 -o out/
uv run python cli.py run ocr.image screenshot.png          # prints text to stdout
uv run python cli.py pipeline my-preset a.pdf -o out/
uv run python cli.py watch ../inbox
```

## API

Interactive docs at `/api/docs`. Every run is a job:

```bash
curl -F files=@a.pdf -F files=@b.pdf -F 'params={"output_name":"both.pdf"}' \
     localhost:8080/api/tools/pdf.merge/run          # -> {"job_id": "..."}
curl localhost:8080/api/jobs/<job_id>                # status, progress, outputs, text, error
curl -O localhost:8080/api/jobs/<job_id>/files/both.pdf
curl -O localhost:8080/api/jobs/<job_id>/zip
curl -X POST localhost:8080/api/jobs/<job_id>/cancel
```

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness and what is missing |
| GET | `/api/tools` | Catalog with JSON Schema for each tool's params |
| POST | `/api/tools/{id}/run` | Multipart `files` + `params` JSON, returns `202 {job_id}` |
| GET | `/api/jobs/{id}` | Status (`queued/running/done/failed/cancelled`), progress, outputs, text, error |
| POST | `/api/jobs/{id}/cancel` | Stop a queued or running job |
| GET | `/api/jobs/{id}/files/{name}` | Download one output |
| GET | `/api/jobs/{id}/zip` | Download all outputs |
| DELETE | `/api/jobs/{id}` | Clean up early |
| GET/POST | `/api/pipelines` | List / create saved pipelines |
| GET/PUT/DELETE | `/api/pipelines/{id}` | Read / update / delete one |
| POST | `/api/pipelines/{id}/run` | Run a saved pipeline on uploaded `files` |
| POST | `/api/pipelines/run` | Run an unsaved pipeline: `files` + `steps` JSON list |

Errors always look like `{"error": {"code", "message", "detail"}}` with codes `validation_error` (422),
`unsupported_file` (415), `too_large` (413), `tool_unavailable` (503), `unknown_tool` (404), `not_found` (404).

## Adding a tool

Create one file under `backend/app/tools/<category>/`. The registry finds it, the API exposes it, the CLI and
pipelines can run it, and the web UI renders its form from the `Params` model. No other file changes.

```python
# backend/app/tools/pdf/rotate.py
from typing import Literal
from pydantic import BaseModel, Field
from pypdf import PdfWriter
from app.core.tool import Tool, ToolContext
from app.tools.pdf._common import open_pdf

class RotateParams(BaseModel):
    degrees: Literal[90, 180, 270] = Field(90, description="Clockwise rotation")

class RotatePdf(Tool):
    id = "pdf.rotate"            # category.verb_object; the prefix must equal `category`
    name = "Rotate PDF"
    category = "pdf"
    description = "Rotate every page."
    accepts = ["application/pdf"]
    batch = True                 # written for one file; the runner calls it once per uploaded file
    Params = RotateParams

    def run(self, files, params, ctx: ToolContext):
        reader = open_pdf(files[0])
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page.rotate(params.degrees))
        out = ctx.out_unique(f"{files[0].stem}-rotated.pdf")
        with out.open("wb") as fh:
            writer.write(fh)
        return [out]
```

Then add a test that references the class name; the registry contract test fails otherwise. Conventions:

- Raise `ToolError("message")` for expected failures. Anything else becomes a generic failure and is logged.
- Write only inside `ctx.workdir` (`ctx.out()`, `ctx.out_unique()`, `ctx.scratch()`).
- Run external programs with `ctx.run_cmd([...])`: an argument list (never a shell), a timeout, merged output
  streamed to an `on_line` callback for progress, and killed if the job is cancelled.
- In long loops call `ctx.check_cancelled()` and `ctx.progress(fraction, message)`.
- Return a `str` for text output (`output = "text"`).
- `requires = ["binary"]`, `requires_py = ["module"]` or an `unmet()` override make the tool degrade
  gracefully when something is missing.
- Browser-only tools go in `frontend/src/client-tools/`.

## Layout

```
backend/app/core/     Tool base class, registry, job runner, pipelines, watch folder, LLM client
backend/app/api/      /api routes (tools, jobs, pipelines)
backend/app/tools/    one file per tool, grouped by category
backend/cli.py        Typer CLI over the same registry
backend/tests/        tool tests, API tests, pipeline/watch tests, registry contract test
frontend/src/         Vite + React + TS (schema-driven forms, dropzone, pipelines, client-side tools)
```

## Security notes

- Uploads are type-checked by content (libmagic), not by extension or the browser's claim. Text playlists
  can therefore never reach ffmpeg's playlist handling, and ffmpeg is also started with a `file`-only
  protocol whitelist.
- `docs.markdown` parses input inside Pandoc's sandbox, strips every image that is not an inline `data:` URI,
  and drops metadata keys that make Pandoc read files, then writes the output from that cleaned document. Without
  this, Markdown such as `![](/etc/passwd)` makes Pandoc embed server files into the output (a test proves it).
- Archive extraction flattens names, skips symlinks and special files, and caps members (5,000) and unpacked
  size (2 GiB). Passworded zip/7z archives are not supported.
- Saved pipeline ids are validated slugs; the watch folder never follows symlinks.
- There is no authentication. Keep the port on localhost, or put it behind your own reverse proxy and auth.

## Known limits

- Jobs run in an in-process thread pool (`TOOLBOX_WORKERS`, default 2). There is no Redis or queue; a server
  restart marks in-flight jobs as failed.
- **Cancel** stops tools that run an external program. A tool that works inside Python (for example `ocr.pdf`
  while OCRmyPDF is running) stops at its next checkpoint rather than immediately.
- `pdf.watermark` is text only. `files.archive` flattens folders into file names (`docs/a.txt` becomes
  `docs_a.txt`).
- `docs.markdown` does not carry over linked local images, only inline `data:` images.
- `ocr.pdf` writes a plain PDF (not PDF/A) and skips pages that already have text by default; use
  `mode=redo` or `force` to override.
- `media.transcribe`, `image.remove_bg` and the Bedrock provider were tested with stand-in modules, not the
  real packages or models (no downloads were possible where this was built).
- The multi-arch GitHub Actions publish workflow (`.github/workflows/publish.yml`) has not been run.
- The UI was built and its logic unit-tested, but it was never opened in a real browser here.
- Hashing and the clipboard button need `https` or `localhost` (Web Crypto and Clipboard APIs).
