import type { JsonSchema, ToolMeta } from "../api/types";

export type ClientResult = string | { image: string; filename: string };

/** A tool that runs entirely in the browser: same metadata shape as a server tool + run(). */
export interface ClientTool extends ToolMeta {
  runtime: "client";
  run: (input: string, params: Record<string, unknown>, input2?: string) => ClientResult | Promise<ClientResult>;
  /** The tool ignores its input box entirely (e.g. the UUID generator). */
  noInput?: boolean;
  /** The tool produces something useful even from empty input (e.g. "now" for timestamps). */
  runsOnEmpty?: boolean;
  /** Label for a second input box (e.g. diff). Its presence turns the box on. */
  secondInput?: string;
  /** Label for the first input box. */
  inputLabel?: string;
  /** What the result is: text (default) or an image data URL. */
  resultType?: "text" | "image";
}

type DefArgs = Pick<ClientTool, "id" | "name" | "category" | "description" | "run"> & {
  schema?: JsonSchema;
  noInput?: boolean;
  runsOnEmpty?: boolean;
  secondInput?: string;
  inputLabel?: string;
  resultType?: "text" | "image";
};

export function def(partial: DefArgs): ClientTool {
  return {
    accepts: [],
    min_files: 0,
    max_files: 0,
    output: "text",
    slow: false,
    runtime: "client",
    available: true,
    missing: [],
    schema: { type: "object", properties: {} },
    ...partial,
  };
}
