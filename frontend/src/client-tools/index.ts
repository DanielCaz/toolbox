import { def, type ClientTool } from "./core";
import { extraTools } from "./extra";

export type { ClientTool } from "./core";

// --- helpers -----------------------------------------------------------------
const encoder = new TextEncoder();
const decoder = new TextDecoder();

function bytesToBinary(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return s;
}

function toHex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function b64urlDecode(part: string): string {
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(part.length / 4) * 4, "=");
  const bin = atob(b64);
  return decoder.decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

function words(s: string): string[] {
  return s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean);
}

function uuidV4(): string {
  const b = crypto.getRandomValues(new Uint8Array(16)); // works on plain http too
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// --- tools -------------------------------------------------------------------
const basicTools: ClientTool[] = [
  def({
    id: "text.base64",
    name: "Base64 encode / decode",
    category: "text",
    description: "Convert text to and from Base64 (UTF-8 safe).",
    schema: {
      type: "object",
      properties: { mode: { type: "string", enum: ["encode", "decode"], default: "encode", description: "Direction" } },
    },
    run: (input, p) =>
      p.mode === "decode"
        ? decoder.decode(Uint8Array.from(atob(input.trim()), (c) => c.charCodeAt(0)))
        : btoa(bytesToBinary(encoder.encode(input))),
  }),
  def({
    id: "text.url",
    name: "URL encode / decode",
    category: "text",
    description: "Percent-encode or decode text for use in URLs.",
    schema: {
      type: "object",
      properties: { mode: { type: "string", enum: ["encode", "decode"], default: "encode", description: "Direction" } },
    },
    run: (input, p) => (p.mode === "decode" ? decodeURIComponent(input) : encodeURIComponent(input)),
  }),
  def({
    id: "text.json",
    name: "JSON formatter",
    category: "text",
    description: "Validate, pretty-print or minify JSON.",
    schema: {
      type: "object",
      properties: {
        mode: { type: "string", enum: ["format", "minify"], default: "format", description: "What to do" },
        indent: { type: "integer", default: 2, minimum: 1, maximum: 8, description: "Indent width for 'format'" },
      },
    },
    run: (input, p) => {
      const value = JSON.parse(input);
      return p.mode === "minify" ? JSON.stringify(value) : JSON.stringify(value, null, Number(p.indent) || 2);
    },
  }),
  def({
    id: "text.case",
    name: "Case converter",
    category: "text",
    description: "UPPER, lower, Title, slug, snake_case or camelCase.",
    schema: {
      type: "object",
      properties: {
        mode: {
          type: "string",
          enum: ["upper", "lower", "title", "slug", "snake", "camel"],
          default: "slug",
          description: "Target case",
        },
      },
    },
    run: (input, p) => {
      switch (p.mode) {
        case "upper":
          return input.toUpperCase();
        case "lower":
          return input.toLowerCase();
        case "title":
          return input.toLowerCase().replace(/\b\p{L}/gu, (c) => c.toUpperCase());
        case "snake":
          return words(input).map((w) => w.toLowerCase()).join("_");
        case "camel":
          return words(input)
            .map((w, i) => (i === 0 ? w.toLowerCase() : w[0].toUpperCase() + w.slice(1).toLowerCase()))
            .join("");
        default:
          return words(input).map((w) => w.toLowerCase()).join("-");
      }
    },
  }),
  def({
    id: "text.lines",
    name: "Line tools",
    category: "text",
    description: "Sort, de-duplicate, reverse or trim lines.",
    schema: {
      type: "object",
      properties: {
        mode: {
          type: "string",
          enum: ["sort", "sort_desc", "dedupe", "reverse", "trim"],
          default: "sort",
          description: "Operation",
        },
      },
    },
    run: (input, p) => {
      const lines = input.split(/\r?\n/);
      switch (p.mode) {
        case "sort_desc":
          return lines.sort((a, b) => b.localeCompare(a)).join("\n");
        case "dedupe":
          return [...new Set(lines)].join("\n");
        case "reverse":
          return lines.reverse().join("\n");
        case "trim":
          return lines.map((l) => l.trim()).filter(Boolean).join("\n");
        default:
          return lines.sort((a, b) => a.localeCompare(b)).join("\n");
      }
    },
  }),
  def({
    id: "dev.uuid",
    name: "UUID generator",
    category: "dev",
    description: "Generate random version-4 UUIDs.",
    noInput: true,
    schema: {
      type: "object",
      properties: { count: { type: "integer", default: 5, minimum: 1, maximum: 100, description: "How many" } },
    },
    run: (_input, p) => Array.from({ length: Math.min(100, Math.max(1, Number(p.count) || 1)) }, uuidV4).join("\n"),
  }),
  def({
    id: "dev.hash",
    name: "Hash text",
    category: "dev",
    description: "SHA-1 / SHA-256 / SHA-384 / SHA-512 of the input text.",
    schema: {
      type: "object",
      properties: {
        algorithm: {
          type: "string",
          enum: ["SHA-256", "SHA-1", "SHA-384", "SHA-512"],
          default: "SHA-256",
          description: "Algorithm",
        },
      },
    },
    run: async (input, p) => {
      if (!crypto.subtle) throw new Error("Hashing needs https or localhost (Web Crypto is unavailable here).");
      return toHex(await crypto.subtle.digest(String(p.algorithm || "SHA-256"), encoder.encode(input)));
    },
  }),
  def({
    id: "dev.jwt",
    name: "JWT decoder",
    category: "dev",
    description: "Read a JWT's header and payload. The signature is not verified.",
    run: (input) => {
      const parts = input.trim().split(".");
      if (parts.length < 2) throw new Error("That does not look like a JWT (expected header.payload.signature).");
      const header = JSON.parse(b64urlDecode(parts[0]));
      const payload = JSON.parse(b64urlDecode(parts[1]));
      const times = ["exp", "iat", "nbf"]
        .filter((k) => typeof payload[k] === "number")
        .map((k) => `${k}: ${new Date(payload[k] * 1000).toISOString()}`);
      return [
        "// header",
        JSON.stringify(header, null, 2),
        "",
        "// payload",
        JSON.stringify(payload, null, 2),
        ...(times.length ? ["", "// times (UTC)", ...times] : []),
      ].join("\n");
    },
  }),
  def({
    id: "dev.timestamp",
    name: "Timestamp converter",
    category: "dev",
    description: "Epoch seconds/milliseconds or a date string, shown every way. Empty input = now.",
    runsOnEmpty: true,
    run: (input) => {
      const s = input.trim();
      let d: Date;
      if (!s) d = new Date();
      else if (/^-?\d+$/.test(s)) d = new Date(s.length <= 11 ? Number(s) * 1000 : Number(s));
      else d = new Date(s);
      if (Number.isNaN(d.getTime())) throw new Error("Could not understand that date or timestamp.");
      return [
        `ISO (UTC):  ${d.toISOString()}`,
        `Local:      ${d.toString()}`,
        `Epoch (s):  ${Math.floor(d.getTime() / 1000)}`,
        `Epoch (ms): ${d.getTime()}`,
      ].join("\n");
    },
  }),
];

export const clientTools: ClientTool[] = [...basicTools, ...extraTools];

export const clientToolsById = new Map(clientTools.map((t) => [t.id, t]));

export const CATEGORY_LABELS: Record<string, string> = {
  pdf: "PDF",
  image: "Images",
  ocr: "OCR",
  docs: "Documents",
  files: "Files & archives",
  qr: "QR & barcodes",
  media: "Audio & video",
  ai: "AI (needs a provider)",
  text: "Text",
  dev: "Developer",
};

export const CATEGORY_ORDER = ["pdf", "image", "ocr", "docs", "files", "qr", "media", "ai", "text", "dev"];
