import { describe, expect, it } from "vitest";
import type { ToolMeta } from "../api/types";
import { describeSteps, fromPipeline, moveStep, newStep, problem, toDefinition } from "./model";

const tool = (id: string, extra: Partial<ToolMeta> = {}): ToolMeta => ({
  id,
  name: id.split(".")[1],
  category: id.split(".")[0],
  description: "",
  accepts: [],
  min_files: 1,
  max_files: 1,
  output: "files",
  slow: false,
  runtime: "server",
  available: true,
  missing: [],
  schema: { properties: { degrees: { type: "integer", default: 90 }, note: { type: "string", default: "" } } },
  ...extra,
});

const tools = new Map([
  ["pdf.rotate", tool("pdf.rotate")],
  ["pdf.extract_text", tool("pdf.extract_text", { output: "text" })],
]);

describe("pipeline editor model", () => {
  it("starts a step from the tool's defaults", () => {
    expect(newStep(1, tools.get("pdf.rotate"))).toEqual({ key: 1, tool: "pdf.rotate", values: { degrees: 90, note: "" } });
    expect(newStep(2, undefined)).toEqual({ key: 2, tool: "", values: {} });
  });

  it("builds a definition without empty options", () => {
    const def = toDefinition("  Tidy  ", " x ", [{ key: 1, tool: "pdf.rotate", values: { degrees: 180, note: "" } }]);
    expect(def).toEqual({ name: "Tidy", description: "x", steps: [{ tool: "pdf.rotate", params: { degrees: 180 } }] });
  });

  it("loads saved params over defaults", () => {
    const steps = fromPipeline(
      { id: "a", name: "A", description: "", steps: [{ tool: "pdf.rotate", params: { degrees: 270 } }] },
      tools,
    );
    expect(steps[0].values).toEqual({ degrees: 270, note: "" });
  });

  it("keeps unknown tools so the problem can be shown instead of losing the step", () => {
    const steps = fromPipeline({ id: "a", name: "A", description: "", steps: [{ tool: "gone.tool", params: { x: 1 } }] }, tools);
    expect(steps).toEqual([{ key: 1, tool: "gone.tool", values: { x: 1 } }]);
    expect(problem(steps, tools)).toBe("Step 1: choose a tool.");
  });

  it("moves steps and ignores moves off the ends", () => {
    expect(moveStep(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
    expect(moveStep(["a", "b", "c"], 1, 1)).toEqual(["a", "c", "b"]);
    const same = ["a", "b"];
    expect(moveStep(same, 0, -1)).toBe(same);
    expect(moveStep(same, 1, 1)).toBe(same);
  });

  it("reports problems in order of importance", () => {
    const rotate = { key: 1, tool: "pdf.rotate", values: {} };
    const text = { key: 2, tool: "pdf.extract_text", values: {} };
    expect(problem([rotate], tools, " ")).toBe("Give the pipeline a name.");
    expect(problem([], tools, "x")).toBe("Add at least one step.");
    expect(problem([text, rotate], tools, "x")).toMatch(/Step 1 \(extract_text\) produces text/);
    expect(problem([rotate, text], tools, "x")).toBeNull();
    expect(problem([rotate], tools)).toBeNull(); // name not checked when running unsaved
  });

  it("describes a pipeline by its tool names", () => {
    const def = { name: "n", description: "", steps: [{ tool: "pdf.rotate", params: {} }, { tool: "x.y", params: {} }] };
    expect(describeSteps(def, tools)).toBe("rotate → x.y");
  });
});
