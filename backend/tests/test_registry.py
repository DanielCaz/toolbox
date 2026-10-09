"""Contract tests: every tool must be well-formed and have a test."""

import re
from pathlib import Path

from app.core.registry import Registry

TESTS_DIR = Path(__file__).parent / "tools"


def test_registry_contract():
    reg = Registry()
    assert len(reg.tools) >= 5

    test_source = "\n".join(p.read_text() for p in TESTS_DIR.glob("test_*.py"))
    for tool_id, tool in reg.tools.items():
        assert re.fullmatch(r"[a-z]+\.[a-z_]+", tool_id), f"bad id {tool_id}"
        assert tool_id.split(".")[0] == tool.category, f"{tool_id}: id prefix != category"
        assert tool.name and tool.description, f"{tool_id}: needs a name and description"
        assert tool.accepts, f"{tool_id}: accepts must be non-empty"
        assert tool.min_files >= 1
        assert tool.max_files is None or tool.max_files >= tool.min_files
        assert tool.output in ("files", "text")
        schema = tool.Params.model_json_schema()
        assert schema["type"] == "object"
        assert type(tool).__name__ in test_source, f"{tool_id}: no test references it"


def test_catalog_shape():
    entry = Registry().catalog()[0]
    for key in (
        "id",
        "name",
        "category",
        "accepts",
        "min_files",
        "max_files",
        "output",
        "available",
        "missing",
        "schema",
        "runtime",
    ):
        assert key in entry
