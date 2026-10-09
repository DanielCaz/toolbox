import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ClientTool } from "../client-tools";
import { CopyButton } from "../components/JobResult";
import { ToolForm, defaultsFor, type FormValues } from "../components/ToolForm";

const storageKey = (id: string) => `toolbox:params:${id}`;

function loadParams(tool: ClientTool): FormValues {
  const defaults = defaultsFor(tool.schema);
  try {
    const saved = localStorage.getItem(storageKey(tool.id));
    if (saved) return { ...defaults, ...JSON.parse(saved) };
  } catch {
    /* storage unavailable or corrupt: use defaults */
  }
  return defaults;
}

/** Browser-only tool: no upload, no server round trip. Output updates as you type. */
export default function ClientToolPage({ tool }: { tool: ClientTool }) {
  const [input, setInput] = useState("");
  const [input2, setInput2] = useState("");
  const [values, setValues] = useState<FormValues>(() => loadParams(tool));
  const [tick, setTick] = useState(0); // bump to re-run (e.g. new UUIDs)
  const [output, setOutput] = useState("");
  const [image, setImage] = useState<{ image: string; filename: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(tool.id), JSON.stringify(values));
    } catch {
      /* ignore */
    }
  }, [tool.id, values]);

  useEffect(() => {
    const empty = input.trim() === "" && input2.trim() === "";
    if (!tool.noInput && !tool.runsOnEmpty && empty) {
      setOutput("");
      setImage(null);
      setError(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const result = await tool.run(input, values, input2);
        if (cancelled) return;
        if (typeof result === "string") {
          setOutput(result);
          setImage(null);
        } else {
          setImage(result);
          setOutput("");
        }
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setOutput("");
        setImage(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    }, 120);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [tool, input, input2, values, tick]);

  const twoInputs = Boolean(tool.secondInput);
  const layout = tool.noInput ? "io single" : twoInputs ? "io three" : "io";

  return (
    <div className="toolpage wide">
      <Link to="/" className="back">
        ← All tools
      </Link>
      <h1>{tool.name}</h1>
      <p className="lede">
        {tool.description} <span className="tag">runs in your browser</span>
      </p>

      {Object.keys(tool.schema.properties ?? {}).length > 0 && (
        <div className="panel">
          <ToolForm schema={tool.schema} values={values} onChange={setValues} />
        </div>
      )}

      <div className={layout}>
        {!tool.noInput && (
          <div className="pane">
            <label htmlFor="ct-input">{tool.inputLabel ?? "Input"}</label>
            <textarea
              id="ct-input"
              spellCheck={false}
              value={input}
              placeholder={tool.runsOnEmpty ? "Leave empty for the current time" : "Paste or type here…"}
              onChange={(e) => setInput(e.target.value)}
            />
          </div>
        )}
        {twoInputs && (
          <div className="pane">
            <label htmlFor="ct-input2">{tool.secondInput}</label>
            <textarea
              id="ct-input2"
              spellCheck={false}
              value={input2}
              placeholder="Paste or type here…"
              onChange={(e) => setInput2(e.target.value)}
            />
          </div>
        )}
        <div className="pane">
          <div className="pane-head">
            <label htmlFor="ct-output">Output</label>
            <span className="rowbtns">
              {tool.noInput && (
                <button type="button" className="btn small" onClick={() => setTick((t) => t + 1)}>
                  Generate again
                </button>
              )}
              {image ? (
                <a className="btn small primary" href={image.image} download={image.filename}>
                  Download PNG
                </a>
              ) : (
                <CopyButton text={output} />
              )}
            </span>
          </div>
          {tool.resultType === "image" ? (
            <div className="imageout">
              {image ? <img src={image.image} alt="Result" /> : <span className="muted">Type something to generate.</span>}
            </div>
          ) : (
            <textarea id="ct-output" readOnly spellCheck={false} value={output} />
          )}
          {error && <p className="note error">{error}</p>}
        </div>
      </div>
    </div>
  );
}
