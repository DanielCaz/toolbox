import type { Pipeline, PipelineDef, ToolMeta } from "../api/types";
import { cleanValues, defaultsFor, type FormValues } from "../components/ToolForm";

/** One step in the editor. `key` is a stable React key (steps get reordered). */
export interface EditorStep {
  key: number;
  tool: string;
  values: FormValues;
}

export const MAX_STEPS = 10;

export function newStep(key: number, tool: ToolMeta | undefined): EditorStep {
  return { key, tool: tool?.id ?? "", values: tool ? defaultsFor(tool.schema) : {} };
}

export function toDefinition(name: string, description: string, steps: EditorStep[]): PipelineDef {
  return {
    name: name.trim(),
    description: description.trim(),
    steps: steps.map((s) => ({ tool: s.tool, params: cleanValues(s.values) })),
  };
}

/** Load a saved pipeline into the editor; missing options fall back to the tool's defaults. */
export function fromPipeline(p: Pipeline, toolsById: Map<string, ToolMeta>): EditorStep[] {
  return p.steps.map((s, i) => {
    const tool = toolsById.get(s.tool);
    return { key: i + 1, tool: s.tool, values: { ...(tool ? defaultsFor(tool.schema) : {}), ...s.params } };
  });
}

export function moveStep<T>(steps: T[], index: number, delta: -1 | 1): T[] {
  const to = index + delta;
  if (to < 0 || to >= steps.length) return steps;
  const next = [...steps];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}

/** A human-readable problem with the editor contents, or null when it can be saved/run. */
export function problem(
  steps: EditorStep[],
  toolsById: Map<string, ToolMeta>,
  name?: string,
): string | null {
  if (name !== undefined && name.trim() === "") return "Give the pipeline a name.";
  if (steps.length === 0) return "Add at least one step.";
  for (const [i, s] of steps.entries()) {
    const tool = toolsById.get(s.tool);
    if (!tool) return `Step ${i + 1}: choose a tool.`;
    if (tool.output === "text" && i < steps.length - 1) {
      return `Step ${i + 1} (${tool.name}) produces text, so it has to be the last step.`;
    }
  }
  return null;
}

export function describeSteps(p: PipelineDef, toolsById: Map<string, ToolMeta>): string {
  return p.steps.map((s) => toolsById.get(s.tool)?.name ?? s.tool).join(" → ");
}
