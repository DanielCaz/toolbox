from __future__ import annotations

import importlib
import importlib.util
import inspect
import pkgutil
import shutil

from app.core.errors import ApiError
from app.core.tool import Tool


def _all_subclasses(cls: type) -> list[type]:
    out: list[type] = []
    for sub in cls.__subclasses__():
        out.append(sub)
        out.extend(_all_subclasses(sub))
    return out


class Registry:
    """Discovers every concrete Tool under ``app/tools`` and builds the catalog."""

    def __init__(self, package: str = "app.tools"):
        self.package = package
        self.tools: dict[str, Tool] = {}
        self._discover()

    def _discover(self) -> None:
        pkg = importlib.import_module(self.package)
        for mod in pkgutil.walk_packages(pkg.__path__, prefix=self.package + "."):
            if mod.name.rsplit(".", 1)[-1].startswith("_"):
                continue  # underscore = helper module, not a tool
            importlib.import_module(mod.name)

        for cls in _all_subclasses(Tool):
            if inspect.isabstract(cls) or not getattr(cls, "id", None):
                continue
            if not cls.__module__.startswith(self.package + "."):
                continue  # e.g. throwaway tools defined in tests
            if cls.id in self.tools:
                raise RuntimeError(f"Duplicate tool id: {cls.id}")
            self.tools[cls.id] = cls()

    # -- lookups ---------------------------------------------------------
    def get(self, tool_id: str) -> Tool:
        try:
            return self.tools[tool_id]
        except KeyError:
            raise ApiError(404, "unknown_tool", f"No tool with id '{tool_id}'.") from None

    @staticmethod
    def missing(tool: Tool) -> list[str]:
        """External binaries and optional Python modules the tool needs but cannot find."""
        out = [b for b in tool.requires if shutil.which(b) is None]
        for mod in tool.requires_py:
            try:
                found = importlib.util.find_spec(mod) is not None
            except (ImportError, ValueError):
                found = False
            if not found:
                out.append(f"python:{mod}")
        out.extend(tool.unmet())
        return out

    def missing_binaries(self) -> list[str]:
        return sorted({b for t in self.tools.values() for b in self.missing(t)})

    # -- catalog ---------------------------------------------------------
    def describe(self, tool: Tool) -> dict:
        missing = self.missing(tool)
        return {
            "id": tool.id,
            "name": tool.name,
            "category": tool.category,
            "description": tool.description,
            "accepts": tool.accepts,
            "min_files": tool.min_files,
            "max_files": tool.max_files,
            "batch": tool.batch,
            "output": tool.output,
            "slow": tool.slow,
            "runtime": "server",
            "available": not missing,
            "missing": missing,
            "schema": tool.Params.model_json_schema(),
        }

    def catalog(self) -> list[dict]:
        ordered = sorted(self.tools.values(), key=lambda t: (t.category, t.id))
        return [self.describe(t) for t in ordered]
