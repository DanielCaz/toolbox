import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { formatBytes } from "../api/client";
import type { ToolMeta } from "../api/types";

function isAccepted(file: File, accepts: string[]): boolean {
  if (!file.type || accepts.length === 0) return true; // the server sniffs content anyway
  return accepts.some((p) => (p.endsWith("/*") ? file.type.startsWith(p.slice(0, -1)) : file.type === p));
}

export function describeAccepts(accepts: string[]): string {
  if (accepts.length === 0) return "any file";
  return accepts
    .map((a) => (a === "application/pdf" ? "PDF" : a === "image/*" ? "images" : a))
    .join(", ");
}

function Thumb({ file }: { file: File }) {
  const url = useMemo(() => (file.type.startsWith("image/") ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => (url ? URL.revokeObjectURL(url) : undefined), [url]);
  if (url) return <img className="thumb" src={url} alt="" />;
  const ext = file.name.includes(".") ? file.name.split(".").pop()!.slice(0, 4).toUpperCase() : "FILE";
  return <span className="thumb badge">{ext}</span>;
}

interface Props {
  tool: ToolMeta;
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
}

export function Dropzone({ tool, files, onChange, disabled }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const single = tool.max_files === 1 && !tool.batch;

  const add = useCallback(
    (incoming: File[]) => {
      if (disabled || incoming.length === 0) return;
      const ok = incoming.filter((f) => isAccepted(f, tool.accepts));
      setNote(
        ok.length < incoming.length
          ? `Skipped ${incoming.length - ok.length} file(s): this tool accepts ${describeAccepts(tool.accepts)}.`
          : null,
      );
      if (ok.length === 0) return;
      let next = single ? [ok[0]] : [...files, ...ok];
      if (tool.max_files !== null && next.length > tool.max_files) next = next.slice(0, tool.max_files);
      onChange(next);
    },
    [disabled, files, onChange, single, tool.accepts, tool.max_files],
  );

  // Ctrl/Cmd+V pastes screenshots and copied files straight into the dropzone.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const pasted = [...(e.clipboardData?.files ?? [])];
      if (pasted.length === 0) return;
      e.preventDefault();
      add(pasted);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [add]);

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= files.length) return;
    const next = [...files];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  };

  return (
    <div>
      <div
        className={`dropzone${over ? " over" : ""}${disabled ? " disabled" : ""}`}
        onClick={() => !disabled && input.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          add([...e.dataTransfer.files]);
        }}
        role="button"
        tabIndex={0}
      >
        <strong>Drop {single ? "a file" : "files"} here</strong>
        <span>
          or click to browse, or paste with Ctrl+V · accepts {describeAccepts(tool.accepts)}
          {tool.min_files > 1 ? ` · at least ${tool.min_files}` : ""}
          {tool.batch ? " · many files are processed one by one" : ""}
        </span>
        <input
          ref={input}
          type="file"
          hidden
          multiple={!single}
          accept={tool.accepts.join(",")}
          onChange={(e) => {
            add([...(e.target.files ?? [])]);
            e.target.value = "";
          }}
        />
      </div>
      {note && <p className="note warn">{note}</p>}

      {files.length > 0 && (
        <ol className="filelist">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <Thumb file={f} />
              <span className="fname" title={f.name}>
                {f.name}
              </span>
              <span className="muted">{formatBytes(f.size)}</span>
              {!single && (
                <span className="rowbtns">
                  <button type="button" aria-label="Move up" disabled={disabled || i === 0} onClick={() => move(i, -1)}>
                    ↑
                  </button>
                  <button
                    type="button"
                    aria-label="Move down"
                    disabled={disabled || i === files.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </button>
                </span>
              )}
              <button
                type="button"
                className="rowbtn"
                aria-label={`Remove ${f.name}`}
                disabled={disabled}
                onClick={() => onChange(files.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
