import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In dev, Vite serves the UI on :5173 and proxies the API to the FastAPI app on :8080.
// In production FastAPI serves the built files itself, so there is one port and no CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://localhost:8080" },
  },
  build: { outDir: "dist" },
  test: { environment: "happy-dom", include: ["src/**/*.test.ts"] },
});
