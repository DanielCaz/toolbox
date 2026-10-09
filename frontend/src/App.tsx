import { Link, Route, Routes } from "react-router-dom";
import Home from "./routes/Home";
import Pipelines from "./routes/Pipelines";
import ToolPage from "./routes/ToolPage";

function NotFound() {
  return (
    <div className="toolpage">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to all tools</Link>
      </p>
    </div>
  );
}

export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="8" fill="currentColor" />
            <path
              d="M9 13h14v9a2 2 0 0 1-2 2H11a2 2 0 0 1-2-2zM12 13v-2a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
              fill="none"
              stroke="white"
              strokeWidth="2"
            />
          </svg>
          Toolbox
        </Link>
        <nav className="topnav">
          <Link to="/pipelines">Pipelines</Link>
        </nav>
        <a className="apilink" href="/api/docs" target="_blank" rel="noreferrer">
          API docs
        </a>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/tool/:id" element={<ToolPage />} />
          <Route path="/pipelines" element={<Pipelines />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </div>
  );
}
