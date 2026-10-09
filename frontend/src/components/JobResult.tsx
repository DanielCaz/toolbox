import { useState } from "react";
import { formatBytes } from "../api/client";
import type { JobStatus } from "../api/types";

const IMAGE_RE = /\.(png|jpe?g|webp|gif|bmp|avif)$/i;

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("done");
    } catch {
      setState("failed"); // clipboard API needs https or localhost
    }
    setTimeout(() => setState("idle"), 1800);
  };
  return (
    <button type="button" className="btn small" onClick={copy}>
      {state === "done" ? "Copied" : state === "failed" ? "Copy failed" : label}
    </button>
  );
}

export function JobResult({ job }: { job: JobStatus }) {
  if (job.status === "queued" || job.status === "running") {
    return (
      <div className="result" aria-live="polite">
        <div className="progress" role="progressbar" aria-valuenow={Math.round(job.progress * 100)}>
          <div style={{ width: `${Math.max(4, job.progress * 100)}%` }} />
        </div>
        <p className="muted">{job.status === "queued" ? "Queued…" : job.message || "Working…"}</p>
      </div>
    );
  }

  if (job.status === "cancelled") {
    return (
      <div className="result" role="status">
        <strong>Cancelled</strong>
        <p className="muted">Nothing was produced. You can adjust the options and run it again.</p>
      </div>
    );
  }

  if (job.status === "failed") {
    return (
      <div className="result error" role="alert">
        <strong>That didn't work.</strong>
        <p>{job.error?.message ?? "Unknown error."}</p>
      </div>
    );
  }

  const files = job.outputs.filter((o) => !(job.text !== null && o.name === "result.txt"));
  return (
    <div className="result ok">
      <strong>Done</strong>
      {job.text !== null && (
        <div className="textout">
          <div className="textout-bar">
            <span className="muted">Extracted text</span>
            <CopyButton text={job.text} />
            <a className="btn small" href={`/api/jobs/${job.id}/files/result.txt`} download>
              Download .txt
            </a>
          </div>
          <pre>{job.text || "(no text found)"}</pre>
        </div>
      )}
      {files.length > 0 && (
        <ul className="outputs">
          {files.map((o) => (
            <li key={o.name}>
              {IMAGE_RE.test(o.name) && <img className="thumb" src={o.url} alt="" />}
              <span className="fname">{o.name}</span>
              <span className="muted">{formatBytes(o.size)}</span>
              <a className="btn small primary" href={o.url} download={o.name}>
                Download
              </a>
            </li>
          ))}
        </ul>
      )}
      {files.length > 1 && (
        <a className="btn" href={`/api/jobs/${job.id}/zip`} download>
          Download all as .zip
        </a>
      )}
      <p className="muted small">Results are deleted from the server automatically after a while.</p>
    </div>
  );
}
