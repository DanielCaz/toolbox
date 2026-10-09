import type { JsonSchema, SchemaProp } from "../api/types";

export type FormValues = Record<string, unknown>;

export function defaultsFor(schema: JsonSchema): FormValues {
  const out: FormValues = {};
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) out[key] = prop.default;
  }
  return out;
}

/** Drop empty strings/NaN so the backend falls back to its own defaults. */
export function cleanValues(values: FormValues): FormValues {
  const out: FormValues = {};
  for (const [k, v] of Object.entries(values)) {
    if (v === "" || v === undefined || (typeof v === "number" && Number.isNaN(v))) continue;
    out[k] = v;
  }
  return out;
}

function label(key: string, prop: SchemaProp): string {
  return prop.title ?? key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

interface Props {
  schema: JsonSchema;
  values: FormValues;
  onChange: (values: FormValues) => void;
  disabled?: boolean;
  /** Needed when several forms share a page (pipeline steps), so element ids stay unique. */
  idPrefix?: string;
}

/** Renders a form straight from a Pydantic/JSON Schema: this is what makes new tools zero-UI-work. */
export function ToolForm({ schema, values, onChange, disabled, idPrefix = "field" }: Props) {
  const entries = Object.entries(schema.properties ?? {});
  if (entries.length === 0) return null;

  const set = (key: string, value: unknown) => onChange({ ...values, [key]: value });

  return (
    <div className="form">
      {entries.map(([key, prop]) => {
        const id = `${idPrefix}-${key}`;
        const value = values[key];
        let control;

        if (prop.enum) {
          control = (
            <select
              id={id}
              value={String(value ?? "")}
              disabled={disabled}
              // keep the option's original type: Literal[90, 180] must be sent as a number, not "90"
              onChange={(e) => set(key, prop.enum!.find((o) => String(o) === e.target.value))}
            >
              {prop.enum.map((opt) => (
                <option key={String(opt)} value={String(opt)}>
                  {String(opt)}
                </option>
              ))}
            </select>
          );
        } else if (prop.type === "boolean") {
          control = (
            <label className="switch">
              <input
                id={id}
                type="checkbox"
                checked={Boolean(value)}
                disabled={disabled}
                onChange={(e) => set(key, e.target.checked)}
              />
              <span>{value ? "On" : "Off"}</span>
            </label>
          );
        } else if (prop.type === "integer" || prop.type === "number") {
          control = (
            <input
              id={id}
              type="number"
              value={value === undefined || value === "" ? "" : Number(value)}
              min={prop.minimum}
              max={prop.maximum}
              step={prop.type === "integer" ? 1 : "any"}
              disabled={disabled}
              onChange={(e) => set(key, e.target.value === "" ? "" : Number(e.target.value))}
            />
          );
        } else {
          control = (
            <input
              id={id}
              type="text"
              value={String(value ?? "")}
              maxLength={prop.maxLength}
              pattern={prop.pattern}
              disabled={disabled}
              onChange={(e) => set(key, e.target.value)}
            />
          );
        }

        return (
          <div className="field" key={key}>
            <label htmlFor={id}>{label(key, prop)}</label>
            {control}
            {prop.description && <p className="hint">{prop.description}</p>}
          </div>
        );
      })}
    </div>
  );
}
