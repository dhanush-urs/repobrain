"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CodeSnippet } from "@/components/common/CodeSnippet";
import { semanticSearch, getFileIntelligence, type FileIntelligenceRecord } from "@/lib/api";
import type { SemanticSearchResponse } from "@/lib/types";
import { Search, Loader2, FileCode, GitBranch, Workflow, MessageSquare, AlertCircle } from "lucide-react";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import { cn } from "@/lib/utils";
// Import canonical role labels/colors from FileFilters (single source of truth)
import { ROLE_LABELS, ROLE_COLORS } from "@/components/repo/FileFilters";

type Props = {
  repoId: string;
};

// ---------------------------------------------------------------------------
// Local path heuristic — fallback only when canonical metadata is missing
// ---------------------------------------------------------------------------

function inferRoleFromPathFallback(path: string): string | null {
  const p = (path || "").toLowerCase().replace("\\", "/");
  const stem = p.split("/").pop()?.split(".")[0] ?? "";
  const parts = p.split("/");
  if (["app", "main", "server", "index", "manage", "wsgi", "asgi"].includes(stem) && parts.length <= 3) return "entrypoint";
  if (/\/(test|tests|spec|specs)\//.test(p) || stem.startsWith("test_") || stem.endsWith("_test")) return "test";
  if (/\/(route|routes|router|controller|handler|endpoint|view|api)\//.test(p)) return "route";
  if (/\/(service|services|usecase|manager)\//.test(p)) return "service";
  if (/\/(repo|repository|dao|store|crud|database|db)\//.test(p)) return "repository";
  if (/\/(schema|schemas)\//.test(p) || stem.endsWith("schema")) return "schema";
  if (/\/(model|models|entity|entities)\//.test(p)) return "model";
  if (/\/(frontend|client|ui|web|pages|components|scripts)\//.test(p) || /\.(jsx|tsx|vue|svelte)$/.test(p)) return "frontend";
  if (/\/(config|settings|env|constants)\//.test(p)) return "config";
  if (/\/(util|utils|helper|helpers|common|shared|lib)\//.test(p)) return "utility";
  return null;
}

// Match type labels
const _MATCH_LABELS: Record<string, string> = {
  exact: "Exact match",
  exact_symbol_definition: "Symbol definition",
  exact_symbol_usage: "Symbol usage",
  partial_symbol_match: "Partial symbol",
  semantic: "Semantic",
  flow_node: "Flow node",
  route_file: "Route file",
  entrypoint: "Entrypoint",
  service_file: "Service file",
  graph_neighbor: "Graph neighbor",
  chunk: "Semantic",
};

export function SearchForm({ repoId }: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SemanticSearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Canonical intelligence — fetched once on mount, used for role badges
  const [intelById, setIntelById] = useState<Map<string, FileIntelligenceRecord>>(new Map());
  const [intelByPath, setIntelByPath] = useState<Map<string, FileIntelligenceRecord>>(new Map());
  const intelFetched = useRef(false);

  useEffect(() => {
    if (intelFetched.current) return;
    intelFetched.current = true;
    getFileIntelligence(repoId, 500).then(res => {
      if (!res.files?.length) return;
      const byId = new Map<string, FileIntelligenceRecord>();
      const byPath = new Map<string, FileIntelligenceRecord>();
      for (const rec of res.files) {
        byId.set(rec.file_id, rec);
        byPath.set(rec.path, rec);
      }
      setIntelById(byId);
      setIntelByPath(byPath);
    }).catch(() => { /* degrade gracefully */ });
  }, [repoId]);

  // Resolve role for a search result: canonical first, path fallback second
  function resolveRole(fileId: string | null | undefined, filePath: string | null | undefined): string | null {
    if (fileId) {
      const rec = intelById.get(fileId);
      if (rec && rec.role && rec.role !== "unknown") return rec.role;
    }
    if (filePath) {
      const rec = intelByPath.get(filePath);
      if (rec && rec.role && rec.role !== "unknown") return rec.role;
      return inferRoleFromPathFallback(filePath);
    }
    return null;
  }

  // Resolve extra signals from canonical intelligence
  function resolveSignals(fileId: string | null | undefined, filePath: string | null | undefined): string | null {
    const rec = (fileId ? intelById.get(fileId) : null) || (filePath ? intelByPath.get(filePath) : null);
    if (!rec) return null;
    const parts: string[] = [];
    if (rec.is_entrypoint) parts.push("entrypoint");
    else if (rec.inbound_edge_count >= 5) parts.push(`↙ ${rec.inbound_edge_count} callers`);
    if (rec.semantic_edge_count >= 2) parts.push(`⬡ ${rec.semantic_edge_count} flow`);
    return parts.length > 0 ? parts[0] : null;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await semanticSearch(repoId, { query, top_k: 8 });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to search repository");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Search toolbar */}
      <form onSubmit={onSubmit}>
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSubmit(e as any);
                }
              }}
              className="w-full h-9 rounded-md border border-white/10 bg-slate-900/60 pl-9 pr-4 text-sm text-white placeholder:text-slate-600 outline-none focus:border-indigo-500/50 transition-colors shadow-sm"
              placeholder="Search by symbol, concept, route, or code pattern..."
            />
          </div>
          <Button
            type="submit"
            disabled={loading || !query.trim()}
            isLoading={loading}
            variant="primary"
            size="sm"
            className="px-4 h-9 shrink-0"
          >
            Search
          </Button>
        </div>
        <p className="mt-2 text-[10px] text-slate-600 px-1 font-medium uppercase tracking-wider">
          Semantic search across indexed code, symbols, and routes
        </p>
      </form>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-sm text-rose-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-rose-500/50 hover:text-rose-400 text-xs">Dismiss</button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-slate-400 py-2">
          <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
          Searching…
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-300">
          <div className="flex items-center justify-between px-1">
            <span className="text-xs text-slate-500">
              {result.total} result{result.total !== 1 ? "s" : ""} for <span className="text-slate-300 font-mono">"{result.query}"</span>
            </span>
          </div>

          {Array.isArray(result.items) && result.items.length > 0 ? (
            <div className="space-y-3">
              {result.items.map((item, idx) => {
                const matchedLines = Array.isArray(item.matched_lines) ? item.matched_lines : [];
                const firstMatchLine = matchedLines.length > 0 ? matchedLines[0] : null;
                const isHighConfidence = item.score > 0.85;
                const hasFileId = item.file_id && item.file_id !== "null";
                const fileHref = hasFileId
                  ? `/repos/${repoId}/files/${item.file_id}${firstMatchLine ? `?line=${firstMatchLine}` : ""}`
                  : null;
                const fileName = item.file_path?.split("/").pop() || "unknown";

                // Canonical role (preferred) or path fallback
                const role = resolveRole(item.file_id, item.file_path);
                const roleLabel = role && role !== "unknown" ? (ROLE_LABELS[role] || role) : null;
                const roleColor = role ? ROLE_COLORS[role] : null;

                // Extra signal from canonical intelligence
                const signal = resolveSignals(item.file_id, item.file_path);

                const matchLabel = item.match_type ? (_MATCH_LABELS[item.match_type] || item.match_type) : "Semantic";

                return (
                  <Card key={item.chunk_id + idx} className="p-0 overflow-hidden border-border/40 bg-slate-900/40 hover:border-indigo-500/20 transition-colors shadow-sm group">
                    {/* File header */}
                    <div className="flex items-center justify-between gap-4 px-4 py-2.5 border-b border-white/5 bg-white/[0.01]">
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        <div className={cn("h-7 w-7 rounded flex items-center justify-center border shrink-0 transition-colors",
                          isHighConfidence ? "bg-indigo-500/10 border-indigo-500/20 text-indigo-400" : "bg-white/[0.02] border-white/5 text-slate-500")}>
                          <FileCode size={14} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <code className="text-[13px] font-semibold text-slate-200 truncate group-hover:text-white transition-colors">{fileName}</code>
                            {roleLabel && roleColor && (
                              <span className={cn("rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider shrink-0", roleColor)}>
                                {roleLabel}
                              </span>
                            )}
                            <span className="text-[9px] font-medium text-slate-500 rounded border border-white/5 px-1.5 py-0.5 shrink-0 uppercase tracking-wider">
                              {matchLabel}
                            </span>
                            {signal && (
                              <span className="text-[9px] text-slate-600 font-mono shrink-0">{signal}</span>
                            )}
                          </div>
                          <div className="flex items-center gap-3 mt-0.5 text-[10px] text-slate-500">
                            <span className="font-mono truncate max-w-[260px] opacity-70">{item.file_path}</span>
                            {firstMatchLine && <span>L{firstMatchLine}</span>}
                            <span className={isHighConfidence ? "text-indigo-400 font-medium" : "text-slate-600"}>
                              {(item.score * 100).toFixed(0)}% match
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-0.5 shrink-0">
                        {fileHref && (
                          <Link href={fileHref} title="View file">
                            <button className="rounded p-1.5 text-slate-500 hover:text-indigo-400 hover:bg-indigo-500/10 transition-colors">
                              <FileCode size={14} />
                            </button>
                          </Link>
                        )}
                        <Link href={`/repos/${repoId}/graph?view=files`} title="Open in graph">
                          <button className="rounded p-1.5 text-slate-500 hover:text-cyan-400 hover:bg-cyan-500/10 transition-colors">
                            <GitBranch size={14} />
                          </button>
                        </Link>
                        {item.file_path && (
                          <Link href={`/repos/${repoId}/flows?mode=file&query=${encodeURIComponent(item.file_path)}`} title="Trace flow">
                            <button className="rounded p-1.5 text-slate-500 hover:text-violet-400 hover:bg-violet-500/10 transition-colors">
                              <Workflow size={14} />
                            </button>
                          </Link>
                        )}
                        <Link href={`/repos/${repoId}/chat`} title="Ask about this">
                          <button className="rounded p-1.5 text-slate-500 hover:text-amber-400 hover:bg-amber-500/10 transition-colors">
                            <MessageSquare size={14} />
                          </button>
                        </Link>
                      </div>
                    </div>

                    {/* Code snippet */}
                    <div className="bg-slate-950/40">
                      <CodeSnippet
                        content={item.snippet || ""}
                        startLine={typeof item.start_line === "number" ? item.start_line : 1}
                        highlightLines={matchedLines}
                        className="py-4 px-5 border-none bg-transparent text-sm"
                      />
                    </div>
                  </Card>
                );
              })}
            </div>
          ) : (
            <Card className="flex flex-col items-center justify-center py-16 text-center border-white/5 bg-slate-900/20">
              <Search className="h-8 w-8 text-slate-600 mb-3" />
              <h3 className="text-sm font-semibold text-white mb-1">No results found</h3>
              <p className="text-xs text-slate-500 max-w-sm">
                No indexed content matched your query. Try different terms, or ensure the repository has been parsed and embedded.
              </p>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
