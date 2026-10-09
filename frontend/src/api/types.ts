export interface SchemaProp {
  type?: "string" | "integer" | "number" | "boolean";
  title?: string;
  description?: string;
  default?: unknown;
  enum?: Array<string | number>;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  pattern?: string;
}

export interface JsonSchema {
  type?: "object";
  properties?: Record<string, SchemaProp>;
}

export interface ToolMeta {
  id: string;
  name: string;
  category: string;
  description: string;
  accepts: string[];
  min_files: number;
  max_files: number | null;
  batch?: boolean;
  output: "files" | "text";
  slow: boolean;
  runtime: "server" | "client";
  available: boolean;
  missing: string[];
  schema: JsonSchema;
}

export interface JobOutput {
  name: string;
  size: number;
  url: string;
}

export type JobState = "queued" | "running" | "done" | "failed" | "cancelled";

export interface JobStatus {
  id: string;
  tool_id: string;
  status: JobState;
  progress: number;
  message: string;
  outputs: JobOutput[];
  text: string | null;
  error: { code: string; message: string } | null;
  created_at: number;
}

export interface PipelineStep {
  tool: string;
  params: Record<string, unknown>;
}

export interface PipelineDef {
  name: string;
  description: string;
  steps: PipelineStep[];
}

export interface Pipeline extends PipelineDef {
  id: string;
}
