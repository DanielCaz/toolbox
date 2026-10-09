import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  cancelJob,
  createPipeline,
  deleteJob,
  deletePipeline,
  fetchPipelines,
  startPipelineJob,
  updatePipeline,
} from "../api/client";
import { useCatalog, useJob } from "../api/hooks";
import type { Pipeline, ToolMeta } from "../api/types";
import { Dropzone } from "../components/Dropzone";
import { JobResult } from "../components/JobResult";
import { ToolForm } from "../components/ToolForm";
import {
  describeSteps,
  fromPipeline,
  MAX_STEPS,
  moveStep,
  newStep,
  problem,
  toDefinition,
  type EditorStep,
} from "../pipelines/model";

export default function Pipelines() {
  const { tools } = useCatalog();
  const qc = useQueryClient();
  const serverTools = useMemo(() => tools.filter((t) => t.runtime === "server" && t.available), [tools]);
  const toolsById = useMemo(() => new Map(serverTools.map((t) => [t.id, t])), [serverTools]);

  const saved = useQuery({ queryKey: ["pipelines"], queryFn: fetchPipelines });

  const nextKey = useRef(1);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<EditorStep[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);

  const issue = problem(steps, toolsById);
  const firstTool = toolsById.get(steps[0]?.tool ?? "");

  const save = useMutation({
    mutationFn: () => {
      const def = toDefinition(name, description, steps);
      return editingId ? updatePipeline(editingId, def) : createPipeline(def);
    },
    onSuccess: (p) => {
      setEditingId(p.id);
      void qc.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deletePipeline(id),
    onSuccess: (_, id) => {
      if (id === editingId) setEditingId(null);
      void qc.invalidateQueries({ queryKey: ["pipelines"] });
    },
  });
  const run = useMutation({
    mutationFn: () => startPipelineJob(files, { steps: toDefinition(name, description, steps).steps }),
    onSuccess: (r) => setJobId(r.job_id),
  });
  const { job, running } = useJob(jobId);
  const busy = run.isPending || running;

  const addStep = () => {
    if (steps.length >= MAX_STEPS) return;
    setSteps([...steps, newStep(nextKey.current++, undefined)]);
  };
  const patch = (key: number, change: Partial<EditorStep>) =>
    setSteps(steps.map((s) => (s.key === key ? { ...s, ...change } : s)));
  const chooseTool = (key: number, toolId: string) => {
    const t = toolsById.get(toolId);
    patch(key, { tool: toolId, values: newStep(key, t).values });
  };
  const load = (p: Pipeline) => {
    nextKey.current = p.steps.length + 1;
    setEditingId(p.id);
    setName(p.name);
    setDescription(p.description);
    setSteps(fromPipeline(p, toolsById));
    setJobId(null);
  };
  const reset = () => {
    setEditingId(null);
    setName("");
    setDescription("");
    setSteps([]);
    setJobId(null);
    setFiles([]);
  };

  return (
    <div className="toolpage">
      <Link to="/" className="back">
        ← All tools
      </Link>
      <h1>Pipelines</h1>
      <p className="lede">
        Chain tools so the result of one feeds the next — for example split a PDF, number its pages, then compress
        it. Save a pipeline to reuse it, or drop files into a watched folder named after it.
      </p>

      {saved.data && saved.data.length > 0 && (
        <div className="panel">
          <h3>Saved pipelines</h3>
          <ul className="pipeline-list">
            {saved.data.map((p) => (
              <li key={p.id} className={p.id === editingId ? "active" : undefined}>
                <div>
                  <strong>{p.name}</strong> <code className="muted">{p.id}</code>
                  <div className="muted">{describeSteps(p, toolsById)}</div>
                </div>
                <span className="row">
                  <button type="button" className="btn small" onClick={() => load(p)}>
                    Open
                  </button>
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => {
                      if (window.confirm(`Delete “${p.name}”?`)) remove.mutate(p.id);
                    }}
                  >
                    Delete
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel">
        <h3>{editingId ? `Editing “${name || editingId}”` : "New pipeline"}</h3>
        <div className="form">
          <div className="field">
            <label htmlFor="pl-name">Name</label>
            <input id="pl-name" type="text" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="pl-desc">Description (optional)</label>
            <input
              id="pl-desc"
              type="text"
              value={description}
              maxLength={300}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </div>

        <ol className="steps">
          {steps.map((s, i) => {
            const tool: ToolMeta | undefined = toolsById.get(s.tool);
            return (
              <li key={s.key} className="step">
                <div className="step-head">
                  <span className="step-n">{i + 1}</span>
                  <select
                    aria-label={`Tool for step ${i + 1}`}
                    value={s.tool}
                    onChange={(e) => chooseTool(s.key, e.target.value)}
                  >
                    <option value="">Choose a tool…</option>
                    {serverTools.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                  <span className="row">
                    <button
                      type="button"
                      className="btn small"
                      aria-label={`Move step ${i + 1} up`}
                      disabled={i === 0}
                      onClick={() => setSteps(moveStep(steps, i, -1))}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      className="btn small"
                      aria-label={`Move step ${i + 1} down`}
                      disabled={i === steps.length - 1}
                      onClick={() => setSteps(moveStep(steps, i, 1))}
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      className="btn small"
                      aria-label={`Remove step ${i + 1}`}
                      onClick={() => setSteps(steps.filter((x) => x.key !== s.key))}
                    >
                      ✕
                    </button>
                  </span>
                </div>
                {tool && (
                  <>
                    <p className="muted">{tool.description}</p>
                    <ToolForm
                      schema={tool.schema}
                      values={s.values}
                      idPrefix={`step${s.key}`}
                      onChange={(values) => patch(s.key, { values })}
                    />
                  </>
                )}
              </li>
            );
          })}
        </ol>

        <div className="actions">
          <button type="button" className="btn" onClick={addStep} disabled={steps.length >= MAX_STEPS}>
            + Add step
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={save.isPending || problem(steps, toolsById, name) !== null}
            onClick={() => save.mutate()}
          >
            {editingId ? "Save changes" : "Save pipeline"}
          </button>
          {(editingId || steps.length > 0) && (
            <button type="button" className="btn" onClick={reset}>
              Clear
            </button>
          )}
        </div>
        {issue && steps.length > 0 && <p className="muted">{issue}</p>}
        {save.error && (
          <p className="note error" role="alert">
            {save.error.message}
          </p>
        )}
        {save.isSuccess && !save.isPending && <p className="muted">Saved.</p>}
      </div>

      {firstTool && !issue && (
        <div className="panel">
          <h3>Run it</h3>
          <Dropzone tool={firstTool} files={files} onChange={setFiles} disabled={busy} />
          <div className="actions">
            <button
              type="button"
              className="btn primary"
              disabled={busy || files.length < firstTool.min_files}
              onClick={() => run.mutate()}
            >
              {busy ? "Working…" : "Run pipeline"}
            </button>
            {running && jobId !== null && (
              <button type="button" className="btn" onClick={() => void cancelJob(jobId)}>
                Cancel
              </button>
            )}
            {jobId !== null && !busy && (
              <button
                type="button"
                className="btn"
                onClick={() => {
                  void deleteJob(jobId);
                  setJobId(null);
                  run.reset();
                }}
              >
                Clear result
              </button>
            )}
          </div>
          {run.error && (
            <p className="note error" role="alert">
              {run.error.message}
            </p>
          )}
          {job.isError && (
            <p className="note error" role="alert">
              This result has expired or was removed. Run the pipeline again.
            </p>
          )}
          {job.data && <JobResult job={job.data} />}
        </div>
      )}
    </div>
  );
}
