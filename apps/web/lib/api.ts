import { API_BASE_URL } from "@/lib/config";
import {
  normalizeRepository,
  normalizeRepositories,
  normalizeRefreshJob,
  normalizeAskRepoResponse,
  normalizeSearchResponse,
  normalizeFileListResponse,
  normalizeHotspotResponse,
  normalizePRImpactResponse,
  normalizeFileDetailResponse,
} from "./normalizers";
import type {
  AskRepoResponse,
  FileDetailResponse,
  FileListResponse,
  HotspotListResponse,
  OnboardingDocumentResponse,
  PRImpactResponse,
  RefreshJob,
  RefreshJobListResponse,
  Repository,
  SemanticSearchResponse,
} from "@/lib/types";

/**
 * Internal helper to enforce a timeout on any promise
 */
async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, errorMessage: string): Promise<T> {
  let timeoutId: any;
  const timeoutPromise = new Promise<T>((_, reject) => {
    timeoutId = setTimeout(() => {
      reject(new Error(errorMessage));
    }, timeoutMs);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => {
    clearTimeout(timeoutId);
  });
}

async function handleResponse<T>(
  response: Response,
  fallback: T,
  timeoutMs: number = 8000
): Promise<T> {
  if (!response.ok) {
    let errorMessage = `API Error ${response.status}`;
    try {
      // Try to get error detail with a short timeout
      const errorData = await withTimeout(
        response.json(),
        2000,
        "Error parsing timeout"
      );
      if (errorData && errorData.detail) {
        errorMessage = typeof errorData.detail === 'string' 
          ? errorData.detail 
          : JSON.stringify(errorData.detail);
      }
    } catch (e) {
      // Not JSON or timed out
    }
    console.error(`[API] ${response.url} failed: ${errorMessage}`);
    throw new Error(errorMessage);
  }

  try {
    // Parse body with a timeout to prevent hanging on stalled streams
    return await withTimeout(
      response.json(),
      timeoutMs,
      `JSON parsing timed out for ${response.url}`
    );
  } catch (err) {
    console.error(`[API] Failed to parse JSON from ${response.url}:`, (err as any).message);
    return fallback;
  }
}

async function safeFetch<T>(
  endpoint: string,
  options: RequestInit = {},
  fallback: T,
  timeoutMs: number = 10000,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = `${API_BASE_URL}${endpoint}`;
    const res = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    
    // We pass half of the remaining timeout or at least 5s to handleResponse
    return await handleResponse(res, fallback, Math.max(5000, timeoutMs / 2));
  } catch (err) {
    const isAbort = (err as any).name === 'AbortError' || (err as any).message?.includes('timeout');
    console.error(`[API] ${isAbort ? 'Timeout' : 'Network error'} on ${endpoint}:`, (err as any).message);
    return fallback;
  } finally {
    clearTimeout(timer);
  }
}

export async function getRepositories(): Promise<Repository[]> {
  const data = await safeFetch("/repos", { cache: "no-store" }, []);
  return normalizeRepositories(data);
}

export async function getJobs(
  repoId: string,
  limit = 1
): Promise<{ items: any[]; total: number }> {
  return safeFetch(
    `/jobs?repo_id=${repoId}&limit=${limit}`,
    { cache: "no-store" },
    { items: [], total: 0 }
  );
}

export async function getRepository(repoId: string): Promise<Repository | null> {
  const data = await safeFetch(`/repos/${repoId}`, { cache: "no-store" }, null);
  return data ? normalizeRepository(data) : null;
}

export async function createRepository(payload: {
  repo_url: string;
  branch: string;
}): Promise<Repository | null> {
  const data = await safeFetch(
    "/repos",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    },
    null
  );
  return data ? normalizeRepository(data) : null;
}

export async function triggerParse(
  repoId: string
): Promise<{ message: string }> {
  return safeFetch(
    `/repos/${repoId}/parse`,
    { method: "POST", cache: "no-store" },
    { message: "Failed to trigger parse" }
  );
}

export async function triggerEmbed(repoId: string): Promise<{
  message: string;
  repository_id: string;
  job_id: string;
  task_id: string;
}> {
  return safeFetch(
    `/repos/${repoId}/embed`,
    { method: "POST", cache: "no-store" },
    {
      message: "Failed to trigger embedding",
      repository_id: repoId,
      job_id: "",
      task_id: "",
    }
  );
}

export async function getRepositoryFiles(
  repoId: string,
  limit = 100
): Promise<FileListResponse> {
  const data = await safeFetch(
    `/repos/${repoId}/files?limit=${limit}`,
    { cache: "no-store" },
    { repository_id: repoId, status: "unknown", items: [], total: 0 }
  );
  return normalizeFileListResponse(data);
}

export async function getRepositoryFileDetail(
  repoId: string,
  fileId: string
): Promise<FileDetailResponse | null> {
  const data = await safeFetch(
    `/repos/${repoId}/files/${fileId}`,
    { cache: "no-store" },
    null
  );
  return data ? normalizeFileDetailResponse(data) : null;
}

export async function semanticSearch(
  repoId: string,
  payload: { query: string; top_k?: number }
): Promise<SemanticSearchResponse> {
  const data = await safeFetch(
    `/repos/${repoId}/search`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    },
    { query: payload.query, results: [] }
  );
  return normalizeSearchResponse(data);
}

export async function askRepo(
  repoId: string,
  payload: { question: string; top_k?: number }
): Promise<AskRepoResponse> {
  const fallback: AskRepoResponse = normalizeAskRepoResponse({
    question: payload.question,
    answer: "The intelligence system is temporarily unavailable.",
    citations: [],
    mode: "general",
  });

  const timeoutMs = 30000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const url = `${API_BASE_URL}/repos/${repoId}/ask`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    
    // For AI queries, we allow more time for JSON parsing as the response can be large
    return normalizeAskRepoResponse(await handleResponse(res, fallback, 20000));
  } catch (err) {
    const isAbort = (err as any).name === 'AbortError' || (err as any).message?.includes('timeout');
    console.error(`[API] askRepo ${isAbort ? 'timeout' : 'error'} for repo ${repoId}:`, (err as any).message);
    return fallback;
  } finally {
    clearTimeout(timer);
  }
}


export async function getHotspots(
  repoId: string
): Promise<HotspotListResponse> {
  const data = await safeFetch(
    `/repos/${repoId}/hotspots?limit=20`,
    { cache: "no-store" },
    { hotspots: [], total: 0 },
    20000,  // 20s — hotspot scoring is CPU-intensive on large repos
  );
  return normalizeHotspotResponse(data);
}

export async function getOnboarding(
  repoId: string
): Promise<OnboardingDocumentResponse | null> {
  return safeFetch(`/repos/${repoId}/onboarding`, { cache: "no-store" }, null);
}

export async function generateOnboarding(repoId: string): Promise<{
  message: string;
  repository_id: string;
  document_id: string;
  generation_mode: string;
  llm_model?: string | null;
}> {
  return safeFetch(
    `/repos/${repoId}/onboarding/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        top_files: 10,
        include_hotspots: true,
        include_search_context: true,
      }),
    },
    {
      message: "Failed to generate onboarding",
      repository_id: repoId,
      document_id: "",
      generation_mode: "standard",
    }
  );
}

export async function analyzeImpact(
  repoId: string,
  payload: { diff?: string; changed_files?: string[]; notes?: string; max_depth?: number }
): Promise<PRImpactResponse> {
  const data = await safeFetch(
    `/repos/${repoId}/impact`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(payload),
    },
    {
      repository_id: repoId,
      changed_files: [],
      impacted_count: 0,
      risk_level: "unknown",
      total_impact_score: 0,
      summary: "Impact analysis unavailable.",
      mode: "error",
      impacted_files: [],
      reviewer_suggestions: [],
      notes: [],
    }
  );
  return normalizePRImpactResponse(data);
}

export async function getRepositoryRefreshJobs(
  repoId: string
): Promise<RefreshJobListResponse> {
  const data = await safeFetch(
    `/jobs?repo_id=${repoId}&limit=50`,
    { cache: "no-store" },
    { items: [] }
  );
  return {
    repository_id: repoId,
    total: Array.isArray(data?.items) ? data.items.length : 0,
    items: Array.isArray(data?.items) ? data.items.map(normalizeRefreshJob) : [],
  };
}

export async function getRefreshJob(jobId: string): Promise<RefreshJob | null> {
  const data = await safeFetch(
    `/jobs/${jobId}`,
    { cache: "no-store" },
    null
  );
  return data ? normalizeRefreshJob(data) : null;
}

export async function getRepoGraph(
  repoId: string,
  params?: {
    edge_types?: string;
    max_nodes?: number;
    min_degree?: number;
  }
): Promise<import("@/lib/types").RepoGraphData> {
  const qs = new URLSearchParams();
  if (params?.edge_types) qs.set("edge_types", params.edge_types);
  if (params?.max_nodes != null) qs.set("max_nodes", String(params.max_nodes));
  if (params?.min_degree != null) qs.set("min_degree", String(params.min_degree));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return safeFetch(
    `/repos/${repoId}/graph/data${query}`,
    { cache: "no-store" },
    { nodes: [], edges: [], total_files: 0, total_resolved_edges: 0, edge_type_counts: {}, truncated: false }
  );
}

export async function getKnowledgeGraph(
  repoId: string,
  params?: {
    view?: "clusters" | "files" | "hotspots" | "impact";
    changed?: string;
    max_nodes?: number;
    edge_types?: string;
  }
): Promise<import("@/lib/types").KnowledgeGraphData> {
  const qs = new URLSearchParams();
  if (params?.view) qs.set("view", params.view);
  if (params?.changed) qs.set("changed", params.changed);
  if (params?.max_nodes != null) qs.set("max_nodes", String(params.max_nodes));
  if (params?.edge_types) qs.set("edge_types", params.edge_types);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return safeFetch(
    `/repos/${repoId}/graph${query}`,
    { cache: "no-store" },
    {
      view: params?.view || "clusters",
      repo_id: repoId,
      nodes: [],
      edges: [],
      legend: {},
      total_files: 0,
      total_resolved_edges: 0,
      truncated: false,
    } as import("@/lib/types").KnowledgeGraphData,
    20000,  // 20s — graph queries can be slow on large repos
  );
}

export async function getExecutionFlow(
  repoId: string,
  params: {
    mode: "route" | "file" | "function" | "impact" | "primary";
    query?: string;
    changed?: string;
    depth?: number;
  }
): Promise<import("@/lib/types").FlowData> {
  const qs = new URLSearchParams();
  qs.set("mode", params.mode);
  if (params.query) qs.set("query", params.query);
  if (params.changed) qs.set("changed", params.changed);
  if (params.depth != null) qs.set("depth", String(params.depth));
  return safeFetch(
    `/repos/${repoId}/flows?${qs.toString()}`,
    { cache: "no-store" },
    {
      mode: params.mode,
      query: params.query || params.changed || "",
      repo_id: repoId,
      summary: { entrypoint: "", estimated_confidence: 0, path_count: 0, notes: [] },
      paths: [],
    } as import("@/lib/types").FlowData,
    20000,  // 20s — flow topology load can be slow on large repos
  );
}


export type FileIntelligenceRecord = {
  file_id: string;
  path: string;
  name: string;
  language: string | null;
  file_kind: string;
  line_count: number;
  role: string;
  role_confidence: number;
  importance_score: number;
  inbound_edge_count: number;
  outbound_edge_count: number;
  semantic_edge_count: number;
  symbol_count: number;
  is_entrypoint: boolean;
  is_frontend: boolean;
  is_generated: boolean;
  is_vendor: boolean;
  is_test: boolean;
};

export type FileIntelligenceResponse = {
  repository_id: string;
  files: FileIntelligenceRecord[];
  total: number;
  error?: string;
};

export async function getFileIntelligence(
  repoId: string,
  limit = 200,
): Promise<FileIntelligenceResponse> {
  return safeFetch(
    `/repos/${repoId}/intelligence?limit=${limit}`,
    { cache: "no-store" },
    { repository_id: repoId, files: [], total: 0 },
    15000,
  );
}
