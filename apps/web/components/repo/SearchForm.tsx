"use client";

import Link from "next/link";
import { useState } from "react";
import { CodeSnippet } from "@/components/common/CodeSnippet";
import { semanticSearch } from "@/lib/api";
import type { SemanticSearchResponse } from "@/lib/types";
import { Search, Loader2, FileCode, CheckCircle2, ChevronRight, Hash, Sparkles, Brain, Layout } from "lucide-react";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import { cn } from "@/lib/utils";

type Props = {
  repoId: string;
};

export function SearchForm({ repoId }: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SemanticSearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await semanticSearch(repoId, {
        query,
        top_k: 8,
      });
      setResult(response);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to search repository"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-12 relative">
      <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-full max-w-4xl h-80 bg-indigo-500/10 blur-[120px] -z-10 pointer-events-none opacity-50" />

      {/* Search Input Area */}
      <div className="animate-in fade-in slide-in-from-top-6 duration-1000">
        <Card className="relative p-0 border-white/10 bg-slate-900/40 backdrop-blur-xl shadow-[0_40px_100px_-20px_rgba(0,0,0,0.8)] overflow-visible rounded-[2rem] inner-glow group">
          <div className="absolute -inset-[1px] bg-gradient-to-r from-indigo-500/30 via-purple-500/30 to-teal-500/30 rounded-[2rem] opacity-0 group-focus-within:opacity-100 transition-opacity duration-1000 blur-sm -z-10" />
          <form onSubmit={onSubmit} className="relative p-3">
            <div className="px-8 pt-10">
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    onSubmit(e as any);
                  }
                }}
                rows={1}
                className="w-full border-none bg-transparent p-0 text-3xl font-black text-white outline-none placeholder:text-slate-700 min-h-[60px] resize-none leading-[1.1] tracking-tighter"
                placeholder="Query repository architecture..."
              />
            </div>
            <div className="flex flex-wrap items-center justify-between px-8 py-6 mt-8 border-t border-white/5">
              <div className="flex items-center gap-6">
                 <div className="flex items-center gap-3 text-[10px] font-black text-slate-500 uppercase tracking-[0.3em] px-4 py-2 rounded-xl bg-slate-950 border border-white/5 shadow-inner group-focus-within:border-indigo-500/30 transition-colors">
                   <div className="h-2 w-2 rounded-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,1)]" />
                   Neural Engine v3.4
                 </div>
                 <div className="hidden lg:flex items-center gap-2 group-focus-within:opacity-100 opacity-0 transition-opacity">
                    <Layout className="h-3.5 w-3.5 text-slate-600" />
                    <span className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Global Graph Enabled</span>
                 </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="hidden sm:block text-[10px] text-slate-500 font-black uppercase tracking-[0.2em] opacity-40">
                  <kbd className="rounded-lg bg-white/5 px-2.5 py-1 border border-white/10 font-sans">Return</kbd> to execute
                </div>
                <Button
                  type="submit"
                  disabled={loading || !query.trim()}
                  isLoading={loading}
                  variant="indigo"
                  className="px-10 h-14 rounded-2xl font-black uppercase text-[11px] tracking-[0.3em] shadow-xl shadow-indigo-500/20 group/btn"
                >
                  Analyze
                  <Sparkles className="ml-3 h-4.5 w-4.5 group-hover:rotate-12 transition-transform" />
                </Button>
              </div>
            </div>
          </form>
        </Card>
      </div>

      {error ? (
        <div className="rounded-[1.5rem] border border-rose-500/20 bg-rose-500/5 p-6 text-sm text-rose-300 flex items-center justify-between gap-6 animate-in fade-in slide-in-from-top-4 shadow-xl">
          <div className="flex items-center gap-4">
            <div className="h-10 w-10 rounded-xl bg-rose-500/10 flex items-center justify-center text-rose-500 ring-1 ring-rose-500/20 shadow-glow/10">
              <Brain className="h-5 w-5" />
            </div>
            <div className="space-y-1">
               <p className="text-[10px] font-black uppercase tracking-[0.3em] text-rose-500/60">Execution Error</p>
               <p className="font-bold text-rose-200 tracking-tight">{error}</p>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setError(null)} className="text-rose-500/40 hover:text-rose-400">Dimiss</Button>
        </div>
      ) : null}

      {result ? (
        <div className="space-y-10 animate-in fade-in slide-in-from-bottom-8 duration-1000">
          <div className="flex items-center justify-between px-4">
            <div className="flex items-center gap-5">
              <div className="h-10 w-10 rounded-xl bg-indigo-500/5 border border-white/5 flex items-center justify-center shadow-inner">
                <Hash className="h-5 w-5 text-indigo-400" />
              </div>
              <div className="space-y-0.5">
                <h3 className="text-[10px] font-black uppercase tracking-[0.4em] text-slate-500">
                  Semantic Extraction Complete
                </h3>
                <p className="text-sm font-bold text-white tracking-tight">{result.total} logical clusters identified</p>
              </div>
            </div>
            {result.items.length > 0 && (
              <div className="flex items-center gap-3 px-5 py-2 rounded-2xl bg-indigo-500/5 border border-indigo-500/10 text-[10px] text-indigo-400 font-extrabold uppercase tracking-[0.25em] animate-pulse-subtle shadow-glow/5">
                <Brain size={14} className="fill-indigo-500/20" />
                Inference Validated
              </div>
            )}
          </div>

          <div className="grid gap-8">
            {Array.isArray(result.items) && result.items.length > 0 ? (
              result.items.map((item, idx) => {
                const matchedLines = Array.isArray(item.matched_lines) ? item.matched_lines : [];
                const firstMatchLine = matchedLines.length > 0 ? matchedLines[0] : null;
                const isExact = item.match_type === "exact" || (item.score > 0.95);

                const hasFileId = item.file_id && item.file_id !== "null";
                const fileHref = hasFileId
                  ? `/repos/${repoId}/files/${item.file_id}${firstMatchLine ? `?line=${firstMatchLine}` : ""}`
                  : null;

                return (
                  <div key={item.chunk_id + idx} className="relative group">
                    <div className="absolute -inset-1 bg-gradient-to-b from-white/[0.03] to-transparent rounded-[2.5rem] blur opacity-50 pointer-events-none" />
                    <Card
                      className={`relative p-0 overflow-hidden transition-all duration-700 bg-slate-950 border-white/[0.08] shadow-[0_30px_70px_-20px_rgba(0,0,0,0.6)] rounded-[2.25rem] inner-glow group/card ${
                        isExact ? "ring-1 ring-indigo-500/20" : ""
                      }`}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-8 border-b border-white/5 px-10 py-7 bg-white/[0.01] relative overflow-hidden">
                        <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-r from-indigo-500/[0.03] via-transparent to-transparent pointer-events-none" />
                        <div className="flex items-center gap-8 min-w-0 flex-1 relative z-10">
                          <div className={cn("h-14 w-14 rounded-2xl flex items-center justify-center border transition-all duration-700 shadow-inner group-hover/card:scale-105", 
                                          isExact ? "bg-indigo-500/10 border-indigo-500/30 text-indigo-400 shadow-[0_0_15px_rgba(99,102,241,0.2)]" : "bg-white/[0.02] border-white/10 text-slate-500")}>
                            <FileCode className="h-7 w-7 opacity-80" />
                          </div>
                          <div className="min-w-0 space-y-2">
                             <div className="flex items-center gap-4">
                                <code className="text-xl font-bold text-white group-hover/card:text-indigo-200 transition-colors tracking-tight truncate">
                                  {item.file_path?.split("/").pop() || "unknown"}
                                </code>
                                {isExact && (
                                  <div className="shrink-0 rounded-xl bg-indigo-500/10 px-3 py-1 text-[9px] font-black uppercase tracking-widest text-indigo-400 border border-indigo-500/20">
                                    High Confidence
                                  </div>
                                )}
                             </div>
                             <div className="flex flex-wrap items-center gap-6 text-[10px] font-bold uppercase tracking-widest">
                               <span className="text-slate-600 font-mono truncate max-w-[300px]">{item.file_path || ""}</span>
                               <span className="h-4 w-[1px] bg-white/5" />
                               <span className="text-slate-500 flex items-center gap-2">
                                  Score: <span className={cn(isExact ? "text-indigo-400" : "text-slate-300")}>{(item.score * 100).toFixed(0)}%</span>
                               </span>
                               {firstMatchLine && (
                                 <>
                                   <span className="h-4 w-[1px] bg-white/5" />
                                   <span className="text-indigo-400/60">Line {firstMatchLine}</span>
                                 </>
                               )}
                             </div>
                          </div>
                        </div>

                        {fileHref && (
                          <Link href={fileHref} className="relative z-10">
                            <Button variant="outline" size="sm" className="h-9 px-5 rounded-xl bg-white/[0.02] border-white/10 hover:bg-white/[0.05] hover:border-indigo-500/50 transition-all">
                              View File
                              <ChevronRight className="ml-2 h-3.5 w-3.5" />
                            </Button>
                          </Link>
                        )}
                      </div>

                      <div className="relative group/code bg-slate-950/40">
                        <CodeSnippet
                          content={item.snippet || ""}
                          startLine={typeof item.start_line === "number" ? item.start_line : 1}
                          highlightLines={matchedLines}
                          className="py-10 px-10 border-none bg-transparent opacity-80 group-hover/card:opacity-100 transition-opacity duration-700"
                        />
                      </div>
                    </Card>
                  </div>
                );
              })
            ) : (
              <Card className="flex flex-col items-center justify-center py-40 text-center border-white/5 bg-slate-900/10 rounded-[3rem] inner-glow group">
                <div className="mb-10 rounded-[2.5rem] bg-slate-950 border border-white/10 p-10 text-slate-700 shadow-inner group-hover:scale-110 group-hover:text-indigo-400 transition-all duration-1000">
                  <Search className="h-16 w-16 opacity-30" />
                </div>
                <h3 className="text-3xl font-black text-white mb-4 tracking-tighter">Negative Signal</h3>
                <p className="text-lg font-medium text-slate-500 max-w-sm mx-auto leading-relaxed">
                  The neural mesh failed to isolate matching logical clusters for your query in the current indexing layer.
                </p>
                <div className="mt-12 flex items-center gap-4 px-6 py-3 rounded-2xl bg-white/[0.02] border border-white/5 animate-pulse-subtle">
                   <div className="h-2 w-2 rounded-full bg-slate-700" />
                   <span className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-600">Global Search Suppressed</span>
                </div>
              </Card>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
