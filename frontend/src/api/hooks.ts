import { useQuery } from "@tanstack/react-query";
import { clientTools } from "../client-tools";
import { fetchJob, fetchTools } from "./client";
import type { ToolMeta } from "./types";

/** Server tools (from /api/tools) merged with the browser-only tools. */
export function useCatalog() {
  const q = useQuery({ queryKey: ["tools"], queryFn: fetchTools, retry: 1 });
  const server: ToolMeta[] = q.data ?? [];
  const tools: ToolMeta[] = [...server, ...clientTools];
  return { tools, offline: q.isError, loading: q.isLoading };
}

const FINISHED = ["done", "failed", "cancelled"];

/** Poll a job until it finishes. */
export function useJob(jobId: string | null) {
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => fetchJob(jobId!),
    enabled: jobId !== null,
    retry: false,
    refetchInterval: (q) => (FINISHED.includes(q.state.data?.status ?? "") ? false : 500),
  });
  const running = jobId !== null && !job.isError && (!job.data || !FINISHED.includes(job.data.status));
  return { job, running };
}
