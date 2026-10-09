import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useCatalog } from "../api/hooks";
import type { ToolMeta } from "../api/types";
import { CATEGORY_LABELS, CATEGORY_ORDER } from "../client-tools";

function Card({ tool }: { tool: ToolMeta }) {
  const body = (
    <>
      <span className="card-title">{tool.name}</span>
      <span className="card-desc">{tool.description}</span>
      <span className="card-tags">
        {tool.runtime === "client" && <span className="tag">in browser</span>}
        {tool.slow && <span className="tag">slow</span>}
        {!tool.available && <span className="tag warn">missing {tool.missing.join(", ")}</span>}
      </span>
    </>
  );
  return tool.available ? (
    <Link className="card" to={`/tool/${tool.id}`}>
      {body}
    </Link>
  ) : (
    <div className="card disabled" aria-disabled="true">
      {body}
    </div>
  );
}

export default function Home() {
  const { tools, offline, loading } = useCatalog();
  const [query, setQuery] = useState("");
  const search = useRef<HTMLInputElement>(null);

  // "/" jumps to search, like most docs sites.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        search.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = tools.filter(
      (t) => !q || [t.name, t.description, t.id, t.category].some((s) => s.toLowerCase().includes(q)),
    );
    const byCat = new Map<string, ToolMeta[]>();
    for (const t of matches) byCat.set(t.category, [...(byCat.get(t.category) ?? []), t]);
    const known = CATEGORY_ORDER.filter((c) => byCat.has(c));
    const extra = [...byCat.keys()].filter((c) => !CATEGORY_ORDER.includes(c)).sort();
    return [...known, ...extra].map((c) => ({ category: c, tools: byCat.get(c)! }));
  }, [tools, query]);

  return (
    <>
      <section className="hero">
        <h1>Everyday tools, on your machine.</h1>
        <p>Files stay on this computer. Pick a tool, drop your files, get the result.</p>
        <input
          ref={search}
          className="search"
          type="search"
          placeholder="Search tools…  ( / )"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search tools"
        />
      </section>

      {offline && (
        <p className="note warn">
          Can't reach the toolbox server, so only the in-browser tools are available right now.
        </p>
      )}
      {loading && <p className="muted">Loading tools…</p>}

      {groups.map((g) => (
        <section key={g.category} className="category">
          <h2>{CATEGORY_LABELS[g.category] ?? g.category}</h2>
          <div className="grid">
            {g.tools.map((t) => (
              <Card key={t.id} tool={t} />
            ))}
          </div>
        </section>
      ))}
      {!loading && groups.length === 0 && <p className="muted">No tools match “{query}”.</p>}
    </>
  );
}
