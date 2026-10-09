import type { JobStatus, Pipeline, PipelineDef, PipelineStep, ToolMeta } from "./types";

export class ApiClientError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function ok(res: Response): Promise<Response> {
  if (res.ok) return res;
  let message = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (body?.error?.message) message = body.error.message;
  } catch {
    /* non-JSON error body: keep the generic message */
  }
  throw new ApiClientError(message, res.status);
}

export async function fetchTools(): Promise<ToolMeta[]> {
  const res = await ok(await fetch("/api/tools"));
  return res.json();
}

export async function startJob(
  toolId: string,
  files: File[],
  params: Record<string, unknown>,
): Promise<{ job_id: string }> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  form.append("params", JSON.stringify(params));
  const res = await ok(await fetch(`/api/tools/${encodeURIComponent(toolId)}/run`, { method: "POST", body: form }));
  return res.json();
}

export async function fetchJob(jobId: string): Promise<JobStatus> {
  const res = await ok(await fetch(`/api/jobs/${jobId}`));
  return res.json();
}

export async function cancelJob(jobId: string): Promise<void> {
  await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" }).catch(() => undefined);
}

export async function deleteJob(jobId: string): Promise<void> {
  await fetch(`/api/jobs/${jobId}`, { method: "DELETE" }).catch(() => undefined);
}

export async function fetchPipelines(): Promise<Pipeline[]> {
  return (await ok(await fetch("/api/pipelines"))).json();
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export async function createPipeline(def: PipelineDef): Promise<Pipeline> {
  return (await ok(await fetch("/api/pipelines", jsonInit("POST", def)))).json();
}

export async function updatePipeline(id: string, def: PipelineDef): Promise<Pipeline> {
  return (await ok(await fetch(`/api/pipelines/${encodeURIComponent(id)}`, jsonInit("PUT", def)))).json();
}

export async function deletePipeline(id: string): Promise<void> {
  await ok(await fetch(`/api/pipelines/${encodeURIComponent(id)}`, { method: "DELETE" }));
}

/** Run a saved pipeline (by id) or an unsaved one (by its steps) on the given files. */
export async function startPipelineJob(
  files: File[],
  target: { id: string } | { steps: PipelineStep[] },
): Promise<{ job_id: string }> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  let url: string;
  if ("id" in target) {
    url = `/api/pipelines/${encodeURIComponent(target.id)}/run`;
  } else {
    url = "/api/pipelines/run";
    form.append("steps", JSON.stringify(target.steps));
  }
  return (await ok(await fetch(url, { method: "POST", body: form }))).json();
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
