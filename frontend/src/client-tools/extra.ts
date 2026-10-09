import cronstrue from "cronstrue";
import { createTwoFilesPatch } from "diff";
import { dump as yamlDump, load as yamlLoad } from "js-yaml";
import QRCode from "qrcode";
import { def, type ClientTool } from "./core";

// ---- helpers ----------------------------------------------------------------
function randomInt(max: number): number {
  // Unbiased random integer in [0, max) from the Web Crypto API.
  const limit = Math.floor(0x100000000 / max) * max;
  const buf = new Uint32Array(1);
  do crypto.getRandomValues(buf);
  while (buf[0] >= limit);
  return buf[0] % max;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

interface Rgb {
  r: number;
  g: number;
  b: number;
}

function parseColor(raw: string): Rgb {
  const s = raw.trim().toLowerCase();
  let m = s.match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/);
  if (m) {
    const h = m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1];
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16) };
  }
  m = s.match(/^rgb\(\s*(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})\s*\)$/);
  if (m) return { r: clamp(+m[1], 0, 255), g: clamp(+m[2], 0, 255), b: clamp(+m[3], 0, 255) };
  m = s.match(/^hsl\(\s*(-?[\d.]+)(?:deg)?[\s,]+([\d.]+)%[\s,]+([\d.]+)%\s*\)$/);
  if (m) {
    const h = (((+m[1] % 360) + 360) % 360) / 360;
    const sat = clamp(+m[2], 0, 100) / 100;
    const l = clamp(+m[3], 0, 100) / 100;
    const q = l < 0.5 ? l * (1 + sat) : l + sat - l * sat;
    const p = 2 * l - q;
    const hue = (t: number) => {
      const x = (t + 1) % 1;
      if (x < 1 / 6) return p + (q - p) * 6 * x;
      if (x < 1 / 2) return q;
      if (x < 2 / 3) return p + (q - p) * (2 / 3 - x) * 6;
      return p;
    };
    return {
      r: Math.round(hue(h + 1 / 3) * 255),
      g: Math.round(hue(h) * 255),
      b: Math.round(hue(h - 1 / 3) * 255),
    };
  }
  throw new Error("Use a colour like #1a73e8, rgb(26, 115, 232) or hsl(217, 80%, 51%).");
}

function toHsl({ r, g, b }: Rgb): [number, number, number] {
  const rn = r / 255,
    gn = g / 255,
    bn = b / 255;
  const max = Math.max(rn, gn, bn),
    min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, Math.round(l * 100)];
  const s = d / (1 - Math.abs(2 * l - 1));
  let h: number;
  if (max === rn) h = ((gn - bn) / d) % 6;
  else if (max === gn) h = (bn - rn) / d + 2;
  else h = (rn - gn) / d + 4;
  return [Math.round(((h * 60 + 360) % 360) * 10) / 10, Math.round(s * 100), Math.round(l * 100)];
}

function luminance({ r, g, b }: Rgb): number {
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// ---- tools ------------------------------------------------------------------
export const extraTools: ClientTool[] = [
  def({
    id: "text.yaml",
    name: "YAML ⇄ JSON",
    category: "text",
    description: "Convert YAML to JSON or JSON to YAML. Validates while it converts.",
    schema: {
      type: "object",
      properties: {
        mode: {
          type: "string",
          enum: ["yaml_to_json", "json_to_yaml"],
          default: "yaml_to_json",
          description: "Direction",
        },
      },
    },
    run: (input, p) => {
      if (p.mode === "json_to_yaml") return yamlDump(JSON.parse(input), { lineWidth: 100, noRefs: true });
      return JSON.stringify(yamlLoad(input), null, 2);
    },
  }),
  def({
    id: "text.regex",
    name: "Regex tester",
    category: "text",
    description: "Try a JavaScript regular expression on some text and see every match and group.",
    inputLabel: "Text to search",
    schema: {
      type: "object",
      properties: {
        pattern: { type: "string", default: "(\\w+)@(\\w+)\\.com", description: "Pattern, without slashes" },
        flags: { type: "string", default: "g", pattern: "^[dgimsuvy]*$", description: "Flags, e.g. gi" },
      },
    },
    run: (input, p) => {
      const flags = String(p.flags ?? "g");
      const re = new RegExp(String(p.pattern ?? ""), flags.includes("g") ? flags : flags + "g");
      const out: string[] = [];
      let count = 0;
      for (const m of input.matchAll(re)) {
        if (m[0] === "" && re.lastIndex === m.index) re.lastIndex++; // avoid infinite empty matches
        count++;
        if (count > 500) {
          out.push("… stopped after 500 matches");
          break;
        }
        out.push(`#${count} at ${m.index}: ${JSON.stringify(m[0])}`);
        for (let i = 1; i < m.length; i++) out.push(`    group ${i}: ${JSON.stringify(m[i] ?? null)}`);
        for (const [name, val] of Object.entries(m.groups ?? {})) out.push(`    ${name}: ${JSON.stringify(val)}`);
      }
      return count === 0 ? "No matches." : `${Math.min(count, 500)} match(es)\n\n${out.join("\n")}`;
    },
  }),
  def({
    id: "text.diff",
    name: "Text diff",
    category: "text",
    description: "Compare two texts and see what changed, in unified diff format.",
    inputLabel: "Original",
    secondInput: "Changed",
    schema: {
      type: "object",
      properties: {
        context: { type: "integer", default: 3, minimum: 0, maximum: 50, description: "Lines of context around changes" },
      },
    },
    run: (a, p, b = "") => {
      if (a === b) return "The two texts are identical.";
      return createTwoFilesPatch("original", "changed", a, b, "", "", { context: Number(p.context ?? 3) });
    },
  }),
  def({
    id: "text.stats",
    name: "Word & character count",
    category: "text",
    description: "Words, characters, lines, sentences and estimated reading time.",
    run: (input) => {
      const words = input.trim() ? input.trim().split(/\s+/).length : 0;
      const sentences = (input.match(/[^.!?]+[.!?]+(\s|$)/g) ?? []).length;
      const lines = input === "" ? 0 : input.split(/\r?\n/).length;
      const minutes = words / 220;
      return [
        `Words:               ${words}`,
        `Characters:          ${[...input].length}`,
        `Characters (no space): ${[...input.replace(/\s/g, "")].length}`,
        `Lines:               ${lines}`,
        `Sentences:           ${sentences}`,
        `Reading time:        ${minutes < 1 ? "under a minute" : `${Math.round(minutes)} min`} (220 wpm)`,
      ].join("\n");
    },
  }),
  def({
    id: "text.html_entities",
    name: "HTML entities",
    category: "text",
    description: "Escape or unescape &, <, >, quotes and non-ASCII characters for HTML.",
    schema: {
      type: "object",
      properties: {
        mode: { type: "string", enum: ["escape", "unescape"], default: "escape", description: "Direction" },
      },
    },
    run: (input, p) => {
      if (p.mode === "unescape") {
        const doc = new DOMParser().parseFromString(input, "text/html");
        return doc.documentElement.textContent ?? "";
      }
      return input
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/[\u0080-￿]/g, (c) => `&#${c.codePointAt(0)};`);
    },
  }),
  def({
    id: "dev.password",
    name: "Password generator",
    category: "dev",
    description: "Random passwords from your browser's cryptographic generator. Nothing is sent anywhere.",
    noInput: true,
    schema: {
      type: "object",
      properties: {
        length: { type: "integer", default: 20, minimum: 8, maximum: 128, description: "Length" },
        count: { type: "integer", default: 5, minimum: 1, maximum: 20, description: "How many" },
        symbols: { type: "boolean", default: true, description: "Include symbols" },
        avoid_lookalikes: { type: "boolean", default: true, description: "Skip look-alikes (0 O 1 l I)" },
      },
    },
    run: (_input, p) => {
      let lower = "abcdefghijklmnopqrstuvwxyz";
      let upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
      let digits = "0123456789";
      const symbols = "!@#$%^&*()-_=+[]{};:,.?";
      if (p.avoid_lookalikes) {
        lower = lower.replace(/[l]/g, "");
        upper = upper.replace(/[IO]/g, "");
        digits = digits.replace(/[01]/g, "");
      }
      const sets = [lower, upper, digits, ...(p.symbols ? [symbols] : [])];
      const all = sets.join("");
      const length = clamp(Number(p.length) || 20, 8, 128);
      const count = clamp(Number(p.count) || 1, 1, 20);
      return Array.from({ length: count }, () => {
        const chars = sets.map((s) => s[randomInt(s.length)]); // one of each class guaranteed
        while (chars.length < length) chars.push(all[randomInt(all.length)]);
        for (let i = chars.length - 1; i > 0; i--) {
          const j = randomInt(i + 1);
          [chars[i], chars[j]] = [chars[j], chars[i]];
        }
        return chars.join("");
      }).join("\n");
    },
  }),
  def({
    id: "dev.color",
    name: "Colour converter",
    category: "dev",
    description: "HEX, RGB and HSL for any colour, plus its contrast against white and black.",
    inputLabel: "Colour (#hex, rgb() or hsl())",
    run: (input) => {
      const c = parseColor(input);
      const [h, s, l] = toHsl(c);
      const hex = "#" + [c.r, c.g, c.b].map((v) => v.toString(16).padStart(2, "0")).join("");
      const vsWhite = contrast(c, { r: 255, g: 255, b: 255 });
      const vsBlack = contrast(c, { r: 0, g: 0, b: 0 });
      const grade = (r: number) => (r >= 7 ? "AAA" : r >= 4.5 ? "AA" : r >= 3 ? "AA large text only" : "fails");
      return [
        `HEX:  ${hex}`,
        `RGB:  rgb(${c.r}, ${c.g}, ${c.b})`,
        `HSL:  hsl(${h}, ${s}%, ${l}%)`,
        "",
        `Contrast on white: ${vsWhite.toFixed(2)}:1 (${grade(vsWhite)})`,
        `Contrast on black: ${vsBlack.toFixed(2)}:1 (${grade(vsBlack)})`,
      ].join("\n");
    },
  }),
  def({
    id: "dev.qr",
    name: "QR code generator",
    category: "dev",
    description: "Turn text or a link into a QR code image you can download.",
    resultType: "image",
    inputLabel: "Text or URL",
    schema: {
      type: "object",
      properties: {
        size: { type: "integer", default: 512, minimum: 128, maximum: 2048, description: "Image size in pixels" },
        error_correction: {
          type: "string",
          enum: ["L", "M", "Q", "H"],
          default: "M",
          description: "Error correction (H survives the most damage but is denser)",
        },
      },
    },
    run: async (input, p) => {
      const image = await QRCode.toDataURL(input, {
        width: clamp(Number(p.size) || 512, 128, 2048),
        margin: 2,
        errorCorrectionLevel: (String(p.error_correction ?? "M") as "L" | "M" | "Q" | "H"),
      });
      return { image, filename: "qr-code.png" };
    },
  }),
  def({
    id: "dev.cron",
    name: "Cron explainer",
    category: "dev",
    description: "Explain a cron expression in plain English (5 or 6 fields).",
    inputLabel: "Cron expression",
    run: (input) => {
      const expr = input.trim();
      const fields = expr.split(/\s+/).length;
      if (fields < 5 || fields > 7) throw new Error("A cron expression has 5 to 7 space-separated fields.");
      return cronstrue.toString(expr, { use24HourTimeFormat: true, verbose: true });
    },
  }),
  def({
    id: "dev.url_parts",
    name: "URL parser",
    category: "dev",
    description: "Split a URL into protocol, host, path, query parameters and fragment.",
    inputLabel: "URL",
    run: (input) => {
      const u = new URL(input.trim());
      const params = [...u.searchParams.entries()];
      return [
        `Protocol: ${u.protocol}`,
        `Host:     ${u.hostname}`,
        `Port:     ${u.port || "(default)"}`,
        `Path:     ${u.pathname}`,
        `Fragment: ${u.hash || "(none)"}`,
        "",
        params.length ? "Query parameters:" : "Query parameters: (none)",
        ...params.map(([k, v]) => `  ${k} = ${v}`),
      ].join("\n");
    },
  }),
];
