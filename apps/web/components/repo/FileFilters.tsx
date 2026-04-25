"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { FileRecord } from "@/lib/types";
import { getFileIntelligence, type FileIntelligenceRecord } from "@/lib/api";
import { Input } from "@/components/common/Input";
import { Search, Filter, FileCode, GitBranch, Workflow, MessageSquare, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  repoId: string;
  files: FileRecord[];
};

// ---------------------------------------------------------------------------
// Canonical role labels and colors — single source of truth
// ---------------------------------------------------------------------------

export const ROLE_LABELS: Record<string, string> = {
  entrypoint: "Entry", route: "Route", service: "Service",
  model: "Model", schema: "Schema", repository: "Repo",
  frontend: "Frontend", api_client: "API Client",
  config: "Config", integration: "Integration",
  middleware: "Middleware", worker: "Worker",
  utility: "Util", test: "Test", unknown: "",
};

export const ROLE_COLORS: Record<string, string> = {
  entrypoint:  "text-rose-400 border-rose-500/20 bg-rose-500/5",
  route:       "text-indigo-400 border-indigo-500/20 bg-indigo-500/5",
  service:     "text-violet-400 border-violet-500/20 bg-violet-500/5",
  model:       "text-emerald-400 border-emerald-500/20 bg-emerald-500/5",
  schema:      "text-teal-400 border-teal-500/20 bg-teal-500/5",
  repository:  "text-cyan-400 border-cyan-500/20 bg-cyan-500/5",
  frontend:    "text-amber-400 border-amber-500/20 bg-amber-500/5",
  api_client:  "text-orange-400 border-orange-500/20 bg-orange-500/5",
  config:      "text-slate-400 border-slate-500/20 bg-slate-500/5",
  integration: "text-pink-400 border-pink-500/20 bg-pink-500/5",
  middleware:  "text-yellow-400 border-yellow-500/20 bg-yellow-500/5",
  worker:      "text-orange-400 border-orange-500/20 bg-orange-500/5",
  utility:     "text-slate-500 border-slate-600/20 bg-slate-600/5",
  test:        "text-slate-600 border-slate-700/20 bg-slate-700/5",
};

// ---------------------------------------------------------------------------
// Local path heuristic — fallback only when canonical metadata is missing
// ---------------------------------------------------------------------------

function inferFileRoleFallback(path: string): string | null {
  const p = path.toLowerCase().replace("\\", "/");
  const stem = p.split("/").pop()?.split(".")[0] ?? "";
  const parts = p.split("/");
  if (["app", "main", "server", "index", "manage", "wsgi", "asgi", "run", "start"].includes(stem) && parts.length <= 3) return "entrypoint";
  if (/\/(test|tests|spec|specs)\//.test(p) || stem.startsWith("test_") || stem.endsWith("_test")) return "test";
  if (/\/(route|routes|router|controller|controllers|handler|handlers|endpoint|endpoints|view|views|api)\//.test(p)) return "route";
  if (/\/(service|services|usecase|use_case|manager|business)\//.test(p)) return "service";
  if (/\/(repo|repository|repositories|dao|store|crud|database|db)\//.test(p)) return "repository";
  if (/\/(schema|schemas)\//.test(p) || stem.endsWith("schema")) return "schema";
  if (/\/(model|models|entity|entities|orm)\//.test(p)) return "model";
  if (/\/(frontend|client|ui|web|pages|components|views|scripts|static)\//.test(p) || /\.(jsx|tsx|vue|svelte)$/.test(p)) return "frontend";
  if (/\/(config|settings|configuration|env|constants)\//.test(p)) return "config";
  if (/\/(util|utils|helper|helpers|common|shared|lib|libs)\//.test(p)) return "utility";
  return null;
}

type SortMode = "importance" | "path";

export function FileFilters({ repoId, files }: Props) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [sortMode, setSortMode] = useState<SortMode>("importance");

  // Canonical intelligence — fetched once, used as primary source
  const [intel, setIntel] = useState<Map<string, FileIntelligenceRecord>>(new Map());
  const [intelByPath, setIntelByPath] = useState<Map<string, FileIntelligenceRecord>>(new Map());

  useEffect(() => {
    let cancelled = false;
    getFileIntelligence(repoId, 500).then(res => {
      if (cancelled || !res.files?.length) return;
      const byId = new Map<string, FileIntelligenceRecord>();
      const byPath = new Map<string, FileIntelligenceRecord>();
      for (const rec of res.files) {
        byId.set(rec.file_id, rec);
        byPath.set(rec.path, rec);
      }
      setIntel(byId);
      setIntelByPath(byPath);
    }).catch(() => { /* degrade gracefully — keep empty maps */ });
    return () => { cancelled = true; };
  }, [repoId]);

  const kinds = useMemo(() => {
    const values = Array.from(new Set(files.map((f) => f.file_kind))).sort();
    return ["all", ...values];
  }, [files]);

  // Enrich each file with canonical intelligence (preferred) or local fallback
  const filesEnriched = useMemo(() => files.map(f => {
    const rec = intel.get(f.id) || intelByPath.get(f.path);
    const role = rec ? rec.role : inferFileRoleFallback(f.path);
    const importanceScore = rec?.importance_score ?? null;
    const inbound = rec?.inbound_edge_count ?? null;
    const semantic = rec?.semantic_edge_count ?? null;
    const symbols = rec?.symbol_count ?? null;
    return { ...f, _role: role, _importance: importanceScore, _inbound: inbound, _semantic: semantic, _symbols: symbols };
  }), [files, intel, intelByPath]);

  const filtered = useMemo(() => {
    let result = filesEnriched.filter((file) => {
      const matchesQuery =
        !query ||
        (file.path || "").toLowerCase().includes(query.toLowerCase()) ||
        (file.language || "").toLowerCase().includes(query.toLowerCase());
      const matchesKind = kind === "all" || (file.file_kind || "file") === kind;
      return matchesQuery && matchesKind;
    });

    if (sortMode === "importance") {
      result = [...result].sort((a, b) => {
        // Prefer canonical importance_score; fall back to role-priority heuristic
        const ia = a._importance;
        const ib = b._importance;
        if (ia !== null && ib !== null) return ib - ia;
        if (ia !== null) return -1;
        if (ib !== null) return 1;
        // Both null — use role priority
        const _ROLE_PRI: Record<string, number> = { entrypoint: 0, route: 1, service: 2, model: 3, schema: 3, repository: 4, frontend: 5, config: 6, utility: 7, test: 8 };
        const pa = a._role ? (_ROLE_PRI[a._role] ?? 9) : 9;
        const pb = b._role ? (_ROLE_PRI[b._role] ?? 9) : 9;
        if (pa !== pb) return pa - pb;
        return a.path.localeCompare(b.path);
      });
    }

    return result;
  }, [filesEnriched, query, kind, sortMode]);

  return (
    <div className="space-y-4 p-4">
      {/* Search + filter + sort bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by path or language..."
            className="pl-10"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-slate-700 shrink-0" />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="rounded-md border border-white/5 bg-slate-900 px-2.5 py-1.5 text-[11px] font-semibold text-slate-400 outline-none focus:border-indigo-500/30 transition-colors"
          >
            {kinds.map((value) => (
              <option key={value} value={value} className="bg-slate-950">
                {value === "all" ? "All types" : value}
              </option>
            ))}
          </select>
          <button
            onClick={() => setSortMode(s => s === "importance" ? "path" : "importance")}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-all",
              sortMode === "importance"
                ? "border-indigo-500/20 bg-indigo-500/5 text-indigo-400"
                : "border-white/5 bg-slate-900 text-slate-600 hover:text-slate-400 hover:bg-white/5"
            )}
            title="Toggle sort: importance / path"
          >
            <ArrowUpDown size={12} />
            {sortMode === "importance" ? "Importance" : "Path"}
          </button>
        </div>
      </div>

      <div className="text-xs text-slate-500 px-1">
        {filtered.length} of {files.length} files
      </div>

      {/* File list */}
      <div className="overflow-hidden rounded-lg border border-border/40 bg-slate-950/40 shadow-premium">
        <div className="grid grid-cols-12 border-b border-white/5 bg-white/[0.01] px-5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-slate-600">
          <div className="col-span-12 sm:col-span-6">File Path</div>
          <div className="hidden sm:col-span-2 sm:block text-center">Role</div>
          <div className="hidden sm:col-span-2 sm:block text-center">Signals</div>
          <div className="hidden sm:col-span-2 sm:block text-right">Actions</div>
        </div>

        <div className="divide-y divide-white/[0.04]">
          {filtered.map((file) => {
            const role = file._role;
            const roleLabel = role && role !== "unknown" ? (ROLE_LABELS[role] || role) : null;
            const roleColor = role ? ROLE_COLORS[role] : null;

            // Compact signals from canonical intelligence
            const signals: string[] = [];
            if (file._inbound && file._inbound >= 3) signals.push(`↙ ${file._inbound}`);
            if (file._semantic && file._semantic >= 1) signals.push(`⬡ ${file._semantic}`);
            if (file._symbols && file._symbols >= 1) signals.push(`ƒ ${file._symbols}`);

            return (
              <div key={file.id} className="group grid grid-cols-12 items-center px-5 py-2.5 hover:bg-white/[0.01] transition-colors relative">
                {/* Path */}
                <div className="col-span-12 sm:col-span-6 flex items-center gap-3 min-w-0">
                  <div className="rounded bg-slate-900/50 p-1.5 text-slate-700 border border-white/5 group-hover:text-indigo-400 group-hover:border-indigo-500/20 transition-all shrink-0 shadow-inner">
                    <FileCode size={14} />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-[13px] text-slate-300 group-hover:text-slate-100 transition-colors font-medium">
                      {file.path}
                    </div>
                    <div className="flex items-center gap-2 sm:hidden mt-0.5">
                      <span className="text-[10px] text-slate-600 font-mono">{file.language || "code"}</span>
                      {roleLabel && roleColor && (
                        <span className={cn("rounded border px-1.5 py-0 text-[9px] font-bold uppercase tracking-wider", roleColor)}>
                          {roleLabel}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Role badge — canonical preferred */}
                <div className="hidden sm:col-span-2 sm:flex items-center justify-center">
                  {roleLabel && roleColor ? (
                    <span className={cn("rounded border px-1.5 py-0 text-[9px] font-bold uppercase tracking-wider", roleColor)}>
                      {roleLabel}
                    </span>
                  ) : (
                    <span className="text-[10px] text-slate-800 tracking-widest">—</span>
                  )}
                </div>

                {/* Signals — from canonical intelligence */}
                <div className="hidden sm:col-span-2 sm:flex items-center justify-center gap-1.5">
                  {signals.length > 0 ? (
                    signals.slice(0, 2).map((s, i) => (
                      <span key={i} className="text-[9px] font-mono text-slate-600 bg-white/[0.02] border border-white/5 rounded px-1 py-0.5">
                        {s}
                      </span>
                    ))
                  ) : (
                    <span className="text-[10px] text-slate-800 font-mono">{file.language || "text"}</span>
                  )}
                </div>

                {/* Quick actions */}
                <div className="hidden sm:col-span-2 sm:flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Link href={`/repos/${repoId}/files/${file.id}`} title="View file">
                    <button className="rounded-lg p-1.5 text-slate-500 hover:text-indigo-400 hover:bg-indigo-500/10 transition-colors">
                      <FileCode className="h-3.5 w-3.5" />
                    </button>
                  </Link>
                  <Link href={`/repos/${repoId}/graph?view=files`} title="Open in graph">
                    <button className="rounded-lg p-1.5 text-slate-500 hover:text-cyan-400 hover:bg-cyan-500/10 transition-colors">
                      <GitBranch className="h-3.5 w-3.5" />
                    </button>
                  </Link>
                  <Link href={`/repos/${repoId}/flows?mode=file&query=${encodeURIComponent(file.path)}`} title="Trace flow">
                    <button className="rounded-lg p-1.5 text-slate-500 hover:text-violet-400 hover:bg-violet-500/10 transition-colors">
                      <Workflow className="h-3.5 w-3.5" />
                    </button>
                  </Link>
                  <Link href={`/repos/${repoId}/chat`} title="Ask about file">
                    <button className="rounded-lg p-1.5 text-slate-500 hover:text-amber-400 hover:bg-amber-500/10 transition-colors">
                      <MessageSquare className="h-3.5 w-3.5" />
                    </button>
                  </Link>
                </div>

                {/* Mobile tap target */}
                <Link href={`/repos/${repoId}/files/${file.id}`} className="absolute inset-0 sm:hidden">
                  <span className="sr-only">View File</span>
                </Link>
              </div>
            );
          })}

          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
              <Search className="h-6 w-6 text-slate-600 mb-3" />
              <h4 className="text-sm font-semibold text-white mb-1">No matches</h4>
              <p className="text-xs text-slate-500">Refine your search or change the type filter.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
