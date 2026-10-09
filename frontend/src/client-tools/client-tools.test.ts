import { describe, expect, it } from "vitest";
import { clientTools, clientToolsById } from "./index";

async function run(id: string, input = "", params: Record<string, unknown> = {}, input2?: string) {
  const tool = clientToolsById.get(id);
  if (!tool) throw new Error(`no tool ${id}`);
  const defaults = Object.fromEntries(
    Object.entries(tool.schema.properties ?? {})
      .filter(([, p]) => p.default !== undefined)
      .map(([k, p]) => [k, p.default]),
  );
  return tool.run(input, { ...defaults, ...params }, input2);
}

describe("catalog", () => {
  it("has unique ids, a known category prefix and a description", () => {
    const ids = clientTools.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of clientTools) {
      expect(t.id.split(".")[0]).toBe(t.category);
      expect(t.description.length).toBeGreaterThan(10);
      expect(t.runtime).toBe("client");
    }
  });
});

describe("text tools", () => {
  it("base64 round-trips unicode", async () => {
    const enc = (await run("text.base64", "héllo ✓", { mode: "encode" })) as string;
    expect(enc).toBe("aMOpbGxvIOKckw==");
    expect(await run("text.base64", enc, { mode: "decode" })).toBe("héllo ✓");
  });

  it("url encode/decode", async () => {
    expect(await run("text.url", "a b&c=d/é")).toBe("a%20b%26c%3Dd%2F%C3%A9");
    expect(await run("text.url", "a%20b", { mode: "decode" })).toBe("a b");
  });

  it("json format, minify and invalid input", async () => {
    expect(await run("text.json", '{"a":1,"b":[1,2]}', { mode: "format", indent: 2 })).toBe(
      '{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}',
    );
    expect(await run("text.json", '{ "a" : 1 }', { mode: "minify" })).toBe('{"a":1}');
    await expect(Promise.resolve().then(() => run("text.json", "{nope"))).rejects.toThrow();
  });

  it("case converter", async () => {
    const c = (mode: string, s = "Hello, Wörld  foo-bar") => run("text.case", s, { mode });
    expect(await c("upper")).toBe("HELLO, WÖRLD  FOO-BAR");
    expect(await c("slug")).toBe("hello-world-foo-bar");
    expect(await c("snake")).toBe("hello_world_foo_bar");
    expect(await c("camel")).toBe("helloWorldFooBar");
    expect(await c("title", "the quick BROWN fox")).toBe("The Quick Brown Fox");
  });

  it("line tools", async () => {
    expect(await run("text.lines", "b\na\nb\nc", { mode: "dedupe" })).toBe("b\na\nc");
    expect(await run("text.lines", "b\na\nc", { mode: "sort" })).toBe("a\nb\nc");
    expect(await run("text.lines", "  x \n\n y", { mode: "trim" })).toBe("x\ny");
  });

  it("yaml <-> json", async () => {
    expect(JSON.parse((await run("text.yaml", "a: 1\nb:\n  - x\n  - y\n")) as string)).toEqual({
      a: 1,
      b: ["x", "y"],
    });
    expect(await run("text.yaml", '{"a":1,"b":["x"]}', { mode: "json_to_yaml" })).toBe("a: 1\nb:\n  - x\n");
    await expect(Promise.resolve().then(() => run("text.yaml", "a: [unclosed"))).rejects.toThrow();
  });

  it("regex tester shows matches and groups, handles empty matches", async () => {
    const out = (await run("text.regex", "ann@acme.com, bob@corp.com", {
      pattern: "(\\w+)@(\\w+)\\.com",
      flags: "g",
    })) as string;
    expect(out).toContain("2 match(es)");
    expect(out).toContain('group 1: "ann"');
    expect(out).toContain('group 2: "corp"');
    expect(await run("text.regex", "abc", { pattern: "x*", flags: "g" })).toContain("match(es)");
    expect(await run("text.regex", "abc", { pattern: "z", flags: "g" })).toBe("No matches.");
    await expect(Promise.resolve().then(() => run("text.regex", "x", { pattern: "(", flags: "g" }))).rejects.toThrow();
  });

  it("diff", async () => {
    expect(await run("text.diff", "same", {}, "same")).toBe("The two texts are identical.");
    const d = (await run("text.diff", "a\nb\nc\n", {}, "a\nB\nc\n")) as string;
    expect(d).toContain("-b");
    expect(d).toContain("+B");
  });

  it("word count", async () => {
    const out = (await run("text.stats", "One two three. Four five!")) as string;
    expect(out).toMatch(/Words:\s+5/);
    expect(out).toMatch(/Sentences:\s+2/);
    expect(out).toMatch(/Lines:\s+1/);
  });

  it("html entities", async () => {
    expect(await run("text.html_entities", `<a href="x">Tom & 'Jerry' é</a>`)).toBe(
      "&lt;a href=&quot;x&quot;&gt;Tom &amp; &#39;Jerry&#39; &#233;&lt;/a&gt;",
    );
    expect(await run("text.html_entities", "&lt;b&gt; &amp; &eacute; &#39;", { mode: "unescape" })).toBe("<b> & é '");
  });
});

describe("developer tools", () => {
  it("uuid v4 format and count", async () => {
    const out = (await run("dev.uuid", "", { count: 4 })) as string;
    const ids = out.split("\n");
    expect(ids).toHaveLength(4);
    for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(new Set(ids).size).toBe(4);
  });

  it("sha-256 of 'abc' matches the known vector", async () => {
    expect(await run("dev.hash", "abc", { algorithm: "SHA-256" })).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    expect(await run("dev.hash", "abc", { algorithm: "SHA-1" })).toBe("a9993e364706816aba3e25717850c26c9cd0d89d");
  });

  it("jwt decoder", async () => {
    const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
    const token = `${b64({ alg: "HS256", typ: "JWT" })}.${b64({ sub: "42", exp: 1893456000 })}.sig`;
    const out = (await run("dev.jwt", token)) as string;
    expect(out).toContain('"sub": "42"');
    expect(out).toContain("exp: 2030-01-01T00:00:00.000Z");
    await expect(Promise.resolve().then(() => run("dev.jwt", "nope"))).rejects.toThrow();
  });

  it("timestamp converter handles seconds, millis, ISO and empty", async () => {
    expect(await run("dev.timestamp", "1700000000")).toContain("2023-11-14T22:13:20.000Z");
    expect(await run("dev.timestamp", "1700000000000")).toContain("Epoch (s):  1700000000");
    expect(await run("dev.timestamp", "2024-02-29T12:00:00Z")).toContain("Epoch (s):  1709208000");
    expect(await run("dev.timestamp", "")).toContain("ISO (UTC):");
    await expect(Promise.resolve().then(() => run("dev.timestamp", "not a date"))).rejects.toThrow();
  });

  it("password generator respects length, count and character classes", async () => {
    const out = (await run("dev.password", "", { length: 24, count: 6, symbols: true })) as string;
    const pws = out.split("\n");
    expect(pws).toHaveLength(6);
    for (const pw of pws) {
      expect(pw).toHaveLength(24);
      expect(pw).toMatch(/[a-z]/);
      expect(pw).toMatch(/[A-Z]/);
      expect(pw).toMatch(/[0-9]/);
      expect(pw).toMatch(/[^A-Za-z0-9]/);
      expect(pw).not.toMatch(/[lIO01]/); // look-alikes avoided by default
    }
    const plain = (await run("dev.password", "", { length: 16, count: 3, symbols: false })) as string;
    for (const pw of plain.split("\n")) expect(pw).toMatch(/^[A-Za-z0-9]{16}$/);
  });

  it("colour converter", async () => {
    const out = (await run("dev.color", "#1a73e8")) as string;
    expect(out).toContain("rgb(26, 115, 232)");
    expect(out).toContain("hsl(214.1, 82%, 51%)");
    expect(await run("dev.color", "#fff")).toContain("#ffffff");
    expect(await run("dev.color", "rgb(255, 0, 0)")).toContain("hsl(0, 100%, 50%)");
    expect(await run("dev.color", "hsl(120, 100%, 25%)")).toContain("#008000");
    expect(await run("dev.color", "#000")).toContain("Contrast on white: 21.00:1 (AAA)");
    await expect(Promise.resolve().then(() => run("dev.color", "blueish"))).rejects.toThrow();
  });

  it("qr generator returns a PNG data URL", async () => {
    const res = await run("dev.qr", "https://example.com", { size: 256, error_correction: "M" });
    expect(typeof res).toBe("object");
    const { image, filename } = res as { image: string; filename: string };
    expect(image.startsWith("data:image/png;base64,")).toBe(true);
    expect(filename).toBe("qr-code.png");
  });

  it("cron explainer", async () => {
    expect(await run("dev.cron", "*/15 9-17 * * 1-5")).toMatch(/every 15 minutes/i);
    await expect(Promise.resolve().then(() => run("dev.cron", "* *"))).rejects.toThrow(/5 to 7/);
  });

  it("url parser", async () => {
    const out = (await run("dev.url_parts", "https://user.example.com:8443/a/b?x=1&y=two#frag")) as string;
    expect(out).toContain("Host:     user.example.com");
    expect(out).toContain("Port:     8443");
    expect(out).toContain("x = 1");
    expect(out).toContain("Fragment: #frag");
  });
});
