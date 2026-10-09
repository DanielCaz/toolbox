import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { cancelJob, deleteJob, fetchJob, startJob } from "../api/client";
import { useCatalog } from "../api/hooks";
import type { ToolMeta } from "../api/types";
import { clientToolsById } from "../client-tools";
import { Dropzone, describeAccepts } from "../components/Dropzone";
import { JobResult } from "../components/JobResult";
import { ToolForm, cleanValues, defaultsFor, type FormValues } from "../components/ToolForm";
import ClientToolPage from "./ClientToolPage";

const storageKey = (id: string) => `toolbox:params:${id}`;

function loadParams(tool: ToolMeta): FormValues {
  const defaults = defaultsFor(tool.schema);
  try {
    const saved = localStorage.getItem(storageKey(tool.id));
    if (saved) return { ...defaults, ...JSON.parse(saved) };
  } catch {
    /* storage unavailable or corrupt: fall back to defaults */
  }
  return defaults;
}

function ServerToolPage({ tool }: { tool: ToolMeta }) {
  const [files, setFiles] = useState<File[]>([]);
  const [values, setValues] = useState<FormValues>(() => loadParams(tool));
  const [jobId, setJobId] = useState<string | null>(null);

  // Remember the last options used for each tool.
  useEffect(() => {
    try {
      localStorage.setItem(storageKey(tool.id), JSON.stringify(values));
    } catch {
      /* ignore */
    }
  }, [tool.id, values]);

  const start = useMutation({
    mutationFn: () => startJob(tool.id, files, cleanValues(values)),
    onSuccess: (r) => setJobId(r.job_id),
  });

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: jobId !== null,
    retry: false,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "done" || s === "failed" || s === "cancelled" ? false : 500;
    },
  });

  const running =
    jobId !== null && !job.isError && (!job.data || job.data.status === "queued" || job.data.status === "running");
  const busy = start.isPending || running;
  const canRun = tool.available && files.length >= tool.min_files && !busy;

  const clear = () => {
    if (jobId) void deleteJob(jobId);
    setJobId(null);
    start.reset();
  };

  const countHint =
    tool.max_files === 1 && !tool.batch
      ? "1 file"
      : tool.min_files > 1
        ? `${tool.min_files}+ files`
        : "one or more files";

  return (
    <div className="toolpage">
      <Link to="/" className="back">
        ← All tools
      </Link>
      <h1>{tool.name}</h1>
      <p className="lede">
        {tool.description}{" "}
        <span className="muted">
          ({describeAccepts(tool.accepts)} · {countHint})
        </span>
      </p>

      <div className="panel">
        <Dropzone tool={tool} files={files} onChange={setFiles} disabled={busy} />
      </div>

      {Object.keys(tool.schema.properties ?? {}).length > 0 && (
        <div className="panel">
          <h3>Options</h3>
          <ToolForm schema={tool.schema} values={values} onChange={setValues} disabled={busy} />
        </div>
      )}

      <div className="actions">
        <button type="button" className="btn primary" disabled={!canRun} onClick={() => start.mutate()}>
          {busy ? "Working…" : "Run"}
        </button>
        {running && jobId !== null && (
          <button type="button" className="btn" onClick={() => void cancelJob(jobId)}>
            Cancel
          </button>
        )}
        {(jobId !== null || files.length > 0) && (
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => {
              clear();
              setFiles([]);
            }}
          >
            Start over
          </button>
        )}
        {files.length < tool.min_files && (
          <span className="muted">
            Add {tool.min_files - files.length} more file{tool.min_files - files.length > 1 ? "s" : ""} to continue
          </span>
        )}
      </div>

      {start.error && (
        <p className="note error" role="alert">
          {start.error.message}
        </p>
      )}
      {job.isError && (
        <p className="note error" role="alert">
          This result has expired or was removed. Run the tool again.
        </p>
      )}
      {job.data && <JobResult job={job.data} />}
    </div>
  );
}

export default function ToolPage() {
  const { id = "" } = useParams();
  const { tools, offline, loading } = useCatalog();

  const client = clientToolsById.get(id);
  if (client) return <ClientToolPage tool={client} />;

  const tool = tools.find((t) => t.id === id);
  if (loading) return <p className="muted">Loading…</p>;
  if (!tool) {
    return (
      <div className="toolpage">
        <Link to="/" className="back">
          ← All tools
        </Link>
        <h1>{offline ? "Server unreachable" : "Tool not found"}</h1>
        <p className="muted">
          {offline
            ? "The toolbox server isn't responding. Check that the container is running."
            : `There is no tool called “${id}”.`}
        </p>
      </div>
    );
  }
  if (!tool.available) {
    return (
      <div className="toolpage">
        <Link to="/" className="back">
          ← All tools
        </Link>
        <h1>{tool.name}</h1>
        <p className="note warn">
          {tool.missing.some((m) => m.startsWith("config:"))
            ? `This tool isn't set up yet: ${tool.missing.join(", ")}. See the README section on AI tools.`
            : `This tool needs ${tool.missing.join(", ")}, which isn't installed on the server.`}
        </p>
      </div>
    );
  }
  return <ServerToolPage key={tool.id} tool={tool} />;
}
