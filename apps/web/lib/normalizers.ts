import {
  Repository,
  RefreshJob,
  AskRepoResponse,
  FileListResponse,
  HotspotListResponse,
  PRImpactResponse,
  SemanticSearchResponse,
  FileDetailResponse,
} from "./types";

/**
 * Normalizes a repository object from the API.
 */
export function normalizeRepository(repo: any): Repository {
  return {
    id: repo?.id || "",
    repo_url: repo?.repo_url || "Unknown Repository",
    default_branch: repo?.default_branch || "main",
    status: repo?.status || "unknown",
    created_at: repo?.created_at || new Date().toISOString(),
    primary_language: repo?.primary_language || null,
    framework: repo?.framework || null,
    languages_used: Array.isArray(repo?.languages_used) ? repo.languages_used : [],
  };
}

/**
 * Normalizes a refresh job object from the API.
 */
export function normalizeRefreshJob(job: any): RefreshJob {
  return {
    id: job.id,
    repository_id: job.repository_id || job.repo_id,
    job_type: job.job_type || job.type || job.event_type || "refresh",
    trigger_source: job.trigger_source || "system",
    event_type: job.event_type || "refresh",
    status: job.status || "pending",
    branch: job.branch,
    summary: job.summary || job.message,
    changed_files: job.changed_files || [],
    created_at: job.created_at,
    error_message: job?.error_message || job.error_details || null,
  };
}

/**
 * Normalizes a list of repositories.
 */
export function normalizeRepositories(data: any): Repository[] {
  if (!data) return [];
  const items = Array.isArray(data) ? data : (data.items || data.repositories || []);
  return items.map(normalizeRepository);
}

/**
 * Normalizes an Ask Repo response.
 */
export function normalizeAskRepoResponse(data: any): AskRepoResponse {
  return {
    question: data?.question || "",
    answer: data?.answer || "No answer provided.",
    citations: (Array.isArray(data?.citations) ? data.citations : []).map((item: any) => ({
      ...item,
      matched_lines: item.matched_lines || [],
    })),
    mode: data?.mode || "general",
    llm_model: data?.llm_model || null,
    confidence: data?.confidence || null,
    notes: Array.isArray(data?.notes) ? data.notes : (Array.isArray(data?.resolution_steps) ? data.resolution_steps : []),
    query_type: data?.query_type || null,
    resolved_file: data?.resolved_file || null,
    resolved_line_number: data?.resolved_line_number || null,
    matched_line: data?.matched_line || null,
    enclosing_scope: data?.enclosing_scope || null,
    line_type: data?.line_type || null,
    rename_analysis: data?.rename_analysis || null,
    answer_mode: data?.answer_mode || null,
    snippet_found: data?.snippet_found || null,
  };
}

/**
 * Normalizes a semantic search response.
 * Ensures all item fields are correctly typed so downstream components never crash.
 */
export function normalizeSearchResponse(data: any): SemanticSearchResponse {
  const rawItems = Array.isArray(data?.items) ? data.items : [];
  const items = rawItems.map((r: any) => ({
    chunk_id: r.chunk_id ?? r.id ?? "",
    file_id: r.file_id ?? null,
    file_path: r.file_path ?? null,
    score: typeof r.score === "number" ? r.score : 0,
    chunk_type: r.chunk_type ?? "code",
    start_line: typeof r.start_line === "number" ? r.start_line : null,
    end_line: typeof r.end_line === "number" ? r.end_line : null,
    matched_lines: Array.isArray(r.matched_lines) ? r.matched_lines.filter((n: any) => typeof n === "number") : [],
    snippet: r.snippet ?? r.content ?? "",
    match_type: r.match_type ?? null,
  }));
  return {
    repository_id: data?.repository_id ?? "",
    query: data?.query ?? "",
    total: typeof data?.total === "number" ? data.total : items.length,
    items,
  };
}


/**
 * Normalizes a file list response.
 */
export function normalizeFileListResponse(data: any): FileListResponse {
  return {
    repository_id: data?.repository_id || "",
    status: data?.status || null,
    total: data?.total || 0,
    items: Array.isArray(data?.items) ? data.items : [],
  };
}

/**
 * Normalizes a hotspot list response.
 */
export function normalizeHotspotResponse(data: any): HotspotListResponse {
  return {
    repository_id: data?.repository_id || "",
    total: data?.total || 0,
    items: Array.isArray(data?.items) ? data.items : [],
  };
}

/**
 * Normalizes a PR impact response.
 */
export function normalizePRImpactResponse(data: any): PRImpactResponse {
  return {
    repository_id: data?.repository_id || "",
    changed_files: Array.isArray(data?.changed_files) ? data.changed_files : [],
    changed_symbols: Array.isArray(data?.changed_symbols) ? data.changed_symbols : [],
    impacted_count: data?.impacted_count || 0,
    risk_level: data?.risk_level || "low",
    total_impact_score: data?.total_impact_score || 0,
    summary: data?.summary || "No summary available.",
    mode: data?.mode || "fallback",
    impacted_files: Array.isArray(data?.impacted_files)
      ? data.impacted_files.map((f: any) => ({
          file_id: f.file_id || "",
          path: f.path || "",
          language: f.language || null,
          depth: f.depth ?? 0,
          inbound_dependencies: f.inbound_dependencies ?? 0,
          outbound_dependencies: f.outbound_dependencies ?? 0,
          risk_score: f.risk_score ?? 0,
          impact_score: f.impact_score ?? 0,
          impact_level: f.impact_level || "low",
          reasons: Array.isArray(f.reasons) ? f.reasons : [],
          edge_types: Array.isArray(f.edge_types) ? f.edge_types : [],
          is_directly_changed: !!f.is_directly_changed,
          categories: Array.isArray(f.categories) ? f.categories : [],
          primary_category: f.primary_category || "module",
          symbol_hits: Array.isArray(f.symbol_hits) ? f.symbol_hits : [],
          why_now: f.why_now || "",
        }))
      : [],
    reviewer_suggestions: Array.isArray(data?.reviewer_suggestions)
      ? data.reviewer_suggestions.map((s: any) => ({
          reviewer_hint: s.reviewer_hint || "",
          reason: s.reason || "",
          why_now: s.why_now || "",
        }))
      : [],
    flow_paths: Array.isArray(data?.flow_paths)
      ? data.flow_paths.map((fp: any) => ({
          summary: fp.summary || "",
          score: fp.score ?? 0,
          nodes: Array.isArray(fp.nodes) ? fp.nodes : [],
        }))
      : [],
    notes: Array.isArray(data?.notes) ? data.notes : [],
  };
}
/**
 * Normalizes a file detail response.
 */
export function normalizeFileDetailResponse(data: any): FileDetailResponse {
  return {
    id: data?.id || "",
    repository_id: data?.repository_id || "",
    path: data?.path || "",
    language: data?.language || null,
    file_kind: data?.file_kind || "text",
    line_count: data?.line_count || 0,
    parse_status: data?.parse_status || "unknown",
    is_generated: !!data?.is_generated,
    is_vendor: !!data?.is_vendor,
    content: data?.content || null,
    raw_url: data?.raw_url || null,
    is_binary: !!data?.is_binary,
  };
}
