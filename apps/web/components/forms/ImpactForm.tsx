"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { analyzeImpact } from "@/lib/api";
import type { PRImpactResponse } from "@/lib/types";
import { Button } from "@/components/common/Button";
import { Card } from "@/components/common/Card";
import {
  Zap, AlertTriangle, FileCode, ChevronRight, ChevronDown,
  Info, Loader2, X, GitBranch, ArrowRight,
  Workflow, MessageSquare, Shield, Activity,
  ListChecks, AlertCircle, Eye, TrendingUp
} from "lucide-react";
import { cn } from "@/lib/utils";

type Props = { repoId: string };

// ---------------------------------------------------------------------------
// Visual config
// ---------------------------------------------------------------------------

const LEVEL_STYLE: Record<string, string> = {
  critical: "text-rose-400 bg-rose-500/10 border-rose-500/30",
  high:     "text-orange-400 bg-orange-500/10 border-orange-500/30",
  medium:   "text-amber-400 bg-amber-500/10 border-amber-500/30",
  low:      "text-emerald-400 bg-emerald-500/10 border-emerald-500/30",
  unknown:  "text-slate-400 bg-slate-500/10 border-slate-500/30",
};

const LEVEL_DOT: Record<string, string> = {
  critical: "bg-rose-500",
  high:     "bg-orange-500",
  medium:   "bg-amber-500",
  low:      "bg-emerald-500",
  unknown:  "bg-slate-500",
};

const CAT_LABEL: Record<string, string> = {
  api_contract:         "API",
  business_logic:       "Logic",
  data_model:           "Model",
  persistence:          "DB",
  auth_security:        "Auth",
  config:               "Config",
  external_integration: "External",
  ui_rendering:         "UI",
  test_only:            "Test",
  infrastructure:       "Infra",
  utility_shared:       "Util",
  module:               "Module",
};

const CAT_COLOR: Record<string, string> = {
  api_contract:         "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
  business_logic:       "text-violet-400 bg-violet-500/10 border-violet-500/20",
  data_model:           "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
  persistence:          "text-teal-400 bg-teal-500/10 border-teal-500/20",
  auth_security:        "text-rose-400 bg-rose-500/10 border-rose-500/20",
  config:               "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  external_integration: "text-pink-400 bg-pink-500/10 border-pink-500/20",
  ui_rendering:         "text-sky-400 bg-sky-500/10 border-sky-500/20",
  test_only:            "text-slate-400 bg-slate-500/10 border-slate-500/20",
  utility_shared:       "text-amber-400 bg-amber-500/10 border-amber-500/20",
  module:               "text-slate-400 bg-slate-500/10 border-slate-500/20",
};

const EXAMPLE_DIFF = `diff --git a/app/services/auth.py b/app/services/auth.py
--- a/app/services/auth.py
+++ b/app/services/auth.py
@@ -12,7 +12,7 @@
-def verify_token(token: str) -> dict:
+def verify_token(token: str, strict: bool = False) -> dict:`;

const SAMPLE_FILES = `app/services/auth.py\napp/api/routes/users.py`;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ImpactForm({ repoId }: Props) {
  const [diff, setDiff] = useState("");
  const [changedFiles, setChangedFiles] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PRImpactResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAllFiles, setShowAllFiles] = useState(false);
  const [showFlowPaths, setShowFlowPaths] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const reqSeq = useRef(0);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!diff.trim() && !changedFiles.trim()) {
      setError("Provide a unified diff or at least one changed file path.");
      return;
    }
    reqSeq.current += 1;
    const seq = reqSeq.current;
    setLoading(true);
    setError(null);
    setResult(null);
    setShowAllFiles(false);
    try {
      const files = changedFiles.split("\n").map(f => f.trim()).filter(Boolean);
      const response = await analyzeImpact(repoId, {
        diff: diff.trim() || undefined,
        changed_files: files.length ? files : undefined,
        notes: notes.trim() || undefined,
        max_depth: 3,
      });
      if (seq !== reqSeq.current) return;
      setResult(response);
    } catch (err) {
      if (seq !== reqSeq.current) return;
      setError(err instanceof Error ? err.message : "Failed to analyze impact");
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }

  const changedCsv = result?.changed_files?.join(",") || "";
  const indirectFiles = result?.impacted_files?.filter(f => !f.is_directly_changed) ?? [];
  const visibleFiles = showAllFiles ? indirectFiles : indirectFiles.slice(0, 5);

  return (
    <div className="space-y-5">
      {/* Input */}
      <Card className="border-white/5 bg-slate-900/30">
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                Unified Diff / Patch
              </label>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => { setDiff(EXAMPLE_DIFF); setChangedFiles(""); }}
                  className="text-[10px] text-slate-600 hover:text-indigo-400 transition-colors">
                  Load sample
                </button>
                <span className="text-slate-700">·</span>
                <button type="button" onClick={() => { setDiff(""); }}
                  className="text-[10px] text-slate-600 hover:text-slate-300 transition-colors">
                  Clear
                </button>
              </div>
            </div>
            <div className="relative">
              <textarea
                value={diff}
                onChange={e => setDiff(e.target.value)}
                rows={7}
                className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-4 py-3 font-mono text-xs text-slate-200 placeholder:text-slate-700 outline-none focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/10 transition-colors resize-y"
                placeholder={EXAMPLE_DIFF}
              />
              {diff && (
                <button type="button" onClick={() => setDiff("")}
                  className="absolute top-2 right-2 text-slate-600 hover:text-slate-300">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-600">
              Paste a unified diff. File paths and changed symbols are extracted automatically.
            </p>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
                Changed Files{" "}
                <span className="text-slate-600 normal-case font-normal">(one per line)</span>
              </label>
              <button type="button" onClick={() => { setChangedFiles(SAMPLE_FILES); setDiff(""); }}
                className="text-[10px] text-slate-600 hover:text-indigo-400 transition-colors">
                Use files only
              </button>
            </div>
            <textarea
              value={changedFiles}
              onChange={e => setChangedFiles(e.target.value)}
              rows={2}
              className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-4 py-3 font-mono text-xs text-slate-200 placeholder:text-slate-700 outline-none focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/10 transition-colors resize-none"
              placeholder={"app/services/auth.py\napp/api/routes/users.py"}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
              PR Notes <span className="text-slate-600 normal-case font-normal">(optional)</span>
            </label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-4 py-3 text-sm text-slate-200 placeholder:text-slate-600 outline-none focus:border-indigo-500/50 focus:ring-2 focus:ring-indigo-500/10 transition-colors resize-none"
              placeholder="Describe what this PR does or any context that helps the analysis..."
            />
          </div>

          <div className="flex items-center gap-3">
            <Button type="submit" variant="indigo" size="md" isLoading={loading}
              disabled={loading || (!diff.trim() && !changedFiles.trim())} className="px-6">
              <Zap className="mr-2 h-4 w-4" />
              Analyze Impact
            </Button>
            {result && (
              <button type="button" onClick={() => { setResult(null); setError(null); }}
                className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
                Clear results
              </button>
            )}
          </div>
        </form>
      </Card>

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-sm text-rose-400">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-3 animate-in fade-in duration-300">
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
            Analyzing impact across the dependency graph…
          </div>
          <div className="space-y-2">
            {[80, 60, 70].map((w, i) => (
              <div key={i} className="h-3 rounded-full bg-white/5 animate-pulse" style={{ width: `${w}%` }} />
            ))}
          </div>
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div className="space-y-5 animate-in fade-in slide-in-from-bottom-4 duration-500">

          {/* Partial failure warning */}
          {result.partial_failure && (
            <div className="flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-2.5 text-xs text-amber-400">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              Partial analysis — some subsystems unavailable: {result.partial_failure_reasons?.join(", ")}
            </div>
          )}

          {/* A) Executive Summary */}
          <Card className="border-indigo-500/20 bg-indigo-500/[0.03]">
            <div className="flex items-center gap-3 mb-3">
              <div className={cn("flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-widest",
                LEVEL_STYLE[result.risk_level] || LEVEL_STYLE.unknown)}>
                <div className={cn("h-1.5 w-1.5 rounded-full", LEVEL_DOT[result.risk_level] || LEVEL_DOT.unknown)} />
                {result.risk_level} risk
              </div>
              <span className="text-xs text-slate-500">{result.total_impact_score.toFixed(1)}/100</span>
              {result.input_extraction && (
                <span className="text-[10px] text-slate-600 rounded-full border border-white/5 px-2 py-0.5">
                  {result.input_extraction.analysis_source === "diff" ? "from diff" :
                   result.input_extraction.analysis_source === "diff+file_list" ? "diff + files" : "file list"}
                </span>
              )}
              <span className="text-[10px] text-slate-600 uppercase tracking-widest ml-auto">
                {result.mode === "gemini_synthesized" ? "AI synthesized" : "Deterministic"}
              </span>
            </div>
            <p className="text-sm text-slate-200 leading-relaxed">{result.executive_summary || result.summary}</p>
            {result.changed_symbols?.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                <span className="text-[10px] text-slate-600 uppercase tracking-widest self-center">Symbols:</span>
                {result.changed_symbols.slice(0, 6).map(s => (
                  <span key={s} className="text-[10px] font-mono text-slate-400 bg-white/[0.03] border border-white/5 rounded px-1.5 py-0.5">{s}</span>
                ))}
              </div>
            )}
            {result.notes?.length > 0 && (
              <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-500/5 border border-amber-500/15 px-3 py-2">
                <Info className="h-3.5 w-3.5 text-amber-400 shrink-0 mt-0.5" />
                <p className="text-[11px] text-amber-400/80">{result.notes[0]}</p>
              </div>
            )}
          </Card>

          {/* B) Summary Metric Cards */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <MetricCard label="Changed" value={result.changed_files.length} icon={<FileCode className="h-3.5 w-3.5" />} color="indigo" />
            <MetricCard label="Impacted" value={result.impacted_count} icon={<Activity className="h-3.5 w-3.5" />} color="orange" />
            <MetricCard label="Modules" value={result.blast_radius?.impacted_modules?.length ?? 0} icon={<GitBranch className="h-3.5 w-3.5" />} color="violet" />
            <MetricCard label="Risk Score" value={`${result.total_impact_score.toFixed(0)}/100`} icon={<Shield className="h-3.5 w-3.5" />}
              color={result.risk_level === "critical" || result.risk_level === "high" ? "rose" : result.risk_level === "medium" ? "amber" : "emerald"} />
            {result.input_extraction && (
              <MetricCard label="Lines" value={`+${result.input_extraction.added_lines} -${result.input_extraction.removed_lines}`} icon={<TrendingUp className="h-3.5 w-3.5" />} color="slate" />
            )}
          </div>

          {/* C) Risk Panel */}
          {result.risk_assessment && result.risk_assessment.risk_reasons.length > 0 && (
            <Card className="border-white/5 bg-slate-900/30">
              <div className="flex items-center gap-2 mb-3">
                <Shield className="h-4 w-4 text-slate-400" />
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest">Risk Assessment</h3>
                <span className={cn("ml-auto rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest",
                  LEVEL_STYLE[result.risk_assessment.overall_risk_level] || LEVEL_STYLE.unknown)}>
                  {result.risk_assessment.overall_risk_level}
                </span>
              </div>
              <div className="space-y-1.5">
                {result.risk_assessment.risk_reasons.map((reason, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-slate-400">
                    <div className="h-1.5 w-1.5 rounded-full bg-amber-500/60 shrink-0 mt-1.5" />
                    {reason}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* D) Changed + Impacted Files */}
          <div className="grid gap-4 md:grid-cols-2">
            {result.changed_files.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">Changed ({result.changed_files.length})</h3>
                <div className="space-y-1.5">
                  {result.changed_files.map(f => (
                    <div key={f} className="flex items-center gap-2 rounded-lg border border-indigo-500/20 bg-indigo-500/5 px-3 py-2">
                      <FileCode className="h-3.5 w-3.5 text-indigo-400 shrink-0" />
                      <span className="text-xs font-mono text-indigo-300 truncate flex-1">{f.split("/").pop()}</span>
                      <span className="text-[10px] text-slate-600 truncate hidden sm:block">{f.includes("/") ? f.split("/").slice(0, -1).join("/") : ""}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {indirectFiles.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2">Impacted ({result.impacted_count})</h3>
                <div className="space-y-1.5">
                  {visibleFiles.map(file => {
                    const dot = LEVEL_DOT[file.impact_level] || LEVEL_DOT.unknown;
                    const catStyle = CAT_COLOR[file.primary_category] || CAT_COLOR.module;
                    const catLabel = CAT_LABEL[file.primary_category] || file.primary_category;
                    const topReason = file.why_now || file.reasons[0] || "";
                    return (
                      <div key={file.file_id} className="flex items-center gap-2 rounded-lg border border-white/5 bg-slate-900/30 px-3 py-2 hover:bg-slate-900/50 transition-colors group">
                        <div className={cn("h-1.5 w-1.5 rounded-full shrink-0", dot)} />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className="text-xs font-mono text-slate-200 truncate">{file.path.split("/").pop()}</span>
                            <span className={cn("shrink-0 rounded-full border px-1.5 py-0 text-[9px] font-semibold uppercase tracking-widest", catStyle)}>{catLabel}</span>
                          </div>
                          {topReason && <p className="text-[10px] text-slate-600 mt-0.5 truncate">{topReason}</p>}
                        </div>
                        <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                          {file.file_id && (
                            <Link href={`/repos/${repoId}/files/${file.file_id}`} title="Open file">
                              <button className="text-slate-500 hover:text-indigo-400 p-1"><FileCode className="h-3 w-3" /></button>
                            </Link>
                          )}
                          <Link href={`/repos/${repoId}/chat`} title="Ask Repo">
                            <button className="text-slate-500 hover:text-indigo-400 p-1"><MessageSquare className="h-3 w-3" /></button>
                          </Link>
                          <Link href={`/repos/${repoId}/flows?mode=file&query=${encodeURIComponent(file.path)}`} title="Trace flow">
                            <button className="text-slate-500 hover:text-indigo-400 p-1"><Workflow className="h-3 w-3" /></button>
                          </Link>
                        </div>
                      </div>
                    );
                  })}
                </div>
                {indirectFiles.length > 5 && (
                  <button onClick={() => setShowAllFiles(v => !v)}
                    className="mt-2 flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-300 transition-colors">
                    <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showAllFiles && "rotate-180")} />
                    {showAllFiles ? "Show less" : `Show ${indirectFiles.length - 5} more`}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* E) Affected Execution Paths */}
          {result.affected_flows && result.affected_flows.length > 0 && (
            <Card className="border-white/5 bg-slate-900/30">
              <div className="flex items-center gap-2 mb-3">
                <Workflow className="h-4 w-4 text-slate-400" />
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest">Affected Execution Paths</h3>
              </div>
              <div className="space-y-2">
                {result.affected_flows.slice(0, 3).map((flow, i) => (
                  <div key={i} className="rounded-lg border border-white/5 bg-slate-950/40 px-3 py-2.5">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-semibold text-slate-300">{flow.flow_name}</span>
                      <span className={cn("text-[9px] font-bold rounded-full border px-1.5 py-0",
                        flow.confidence >= 0.6 ? "text-emerald-400 border-emerald-500/20 bg-emerald-500/10" : "text-slate-500 border-white/5 bg-white/[0.02]")}>
                        {Math.round(flow.confidence * 100)}%
                      </span>
                      <Link href={`/repos/${repoId}/flows?mode=impact&changed=${encodeURIComponent(result.changed_files.join(","))}`}
                        className="ml-auto text-[10px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
                        Open Map <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>
                    <p className="text-[11px] text-slate-500 leading-relaxed">{flow.summary || flow.why_relevant}</p>
                    {flow.path_nodes.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1 mt-1.5">
                        {flow.path_nodes.slice(0, 5).map((n, j) => (
                          <span key={j} className="text-[10px] text-slate-600 font-mono">
                            {n}{j < Math.min(flow.path_nodes.length, 5) - 1 && <span className="text-slate-700 mx-1">→</span>}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* F) Review Checklist */}
          {(result.review_priorities?.length || result.reviewer_suggestions.length > 0) && (
            <Card className="border-white/5 bg-slate-900/30">
              <div className="flex items-center gap-2 mb-3">
                <ListChecks className="h-4 w-4 text-slate-400" />
                <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest">Review Checklist</h3>
              </div>
              <div className="space-y-2">
                {(result.review_priorities?.length ? result.review_priorities : result.reviewer_suggestions.map(s => ({
                  file_id: null as string | null | undefined,
                  path: s.reason.split(" — ")[0] || s.reviewer_hint,
                  reason: s.why_now || s.reason,
                  priority_score: 0,
                  primary_category: "module",
                }))).slice(0, 6).map((item, i) => {
                  const catStyle = CAT_COLOR[item.primary_category] || CAT_COLOR.module;
                  const catLabel = CAT_LABEL[item.primary_category] || item.primary_category;
                  return (
                    <div key={i} className="flex items-start gap-3 rounded-lg border border-white/5 bg-slate-900/20 px-3 py-2.5 group">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-800 text-[9px] font-bold text-indigo-400 ring-1 ring-white/10 mt-0.5">{i + 1}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-xs font-mono text-slate-300 truncate">{item.path?.split("/").pop()}</span>
                          <span className={cn("shrink-0 rounded-full border px-1.5 py-0 text-[9px] font-semibold uppercase tracking-widest", catStyle)}>{catLabel}</span>
                        </div>
                        {item.reason && <p className="text-[11px] text-slate-500 mt-0.5 leading-snug">{item.reason}</p>}
                      </div>
                      <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                        {item.file_id && (
                          <Link href={`/repos/${repoId}/files/${item.file_id}`}>
                            <button className="text-slate-500 hover:text-indigo-400 p-1"><FileCode className="h-3 w-3" /></button>
                          </Link>
                        )}
                        <Link href={`/repos/${repoId}/chat`}>
                          <button className="text-slate-500 hover:text-indigo-400 p-1"><MessageSquare className="h-3 w-3" /></button>
                        </Link>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {/* G) Possible Regressions */}
          {result.possible_regressions && result.possible_regressions.length > 0 && (
            <Card className="border-amber-500/10 bg-amber-500/[0.02]">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="h-4 w-4 text-amber-400" />
                <h3 className="text-xs font-semibold text-amber-400/80 uppercase tracking-widest">Possible Regressions</h3>
              </div>
              <div className="space-y-1.5">
                {result.possible_regressions.map((reg, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className={cn("shrink-0 rounded-full border px-1.5 py-0 text-[9px] font-bold uppercase tracking-widest mt-0.5",
                      reg.confidence === "likely" ? "text-orange-400 border-orange-500/20 bg-orange-500/10" : "text-amber-400 border-amber-500/20 bg-amber-500/10")}>
                      {reg.confidence}
                    </span>
                    <span className="text-slate-400">{reg.description}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* H) Evidence */}
          {result.evidence && result.evidence.length > 0 && (
            <div>
              <button onClick={() => setShowEvidence(v => !v)}
                className="flex items-center gap-2 text-xs text-slate-500 hover:text-slate-300 transition-colors">
                <Eye className="h-3.5 w-3.5" />
                <span className="uppercase tracking-widest font-semibold">Why RepoBrain thinks this ({result.evidence.length})</span>
                <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", showEvidence && "rotate-90")} />
              </button>
              {showEvidence && (
                <div className="mt-2 space-y-1.5 animate-in fade-in duration-200">
                  {result.evidence.map((ev, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg border border-white/5 bg-slate-900/20 px-3 py-2">
                      <Info className="h-3 w-3 text-slate-600 shrink-0 mt-0.5" />
                      <div className="min-w-0">
                        <span className="text-[11px] text-slate-400">{ev.signal}</span>
                        {ev.file_path && <span className="text-[10px] text-slate-600 font-mono ml-2">{ev.file_path.split("/").pop()}</span>}
                        {ev.detail && <p className="text-[10px] text-slate-600 mt-0.5">{ev.detail}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Integration links */}
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-white/5">
            {changedCsv && (
              <Link href={`/repos/${repoId}/graph?view=impact&changed=${encodeURIComponent(changedCsv)}`}>
                <Button variant="ghost" size="sm" className="text-xs h-7">
                  <GitBranch className="mr-1.5 h-3.5 w-3.5" />Knowledge Graph
                </Button>
              </Link>
            )}
            {changedCsv && (
              <Link href={`/repos/${repoId}/flows?mode=impact&changed=${encodeURIComponent(changedCsv)}`}>
                <Button variant="ghost" size="sm" className="text-xs h-7">
                  <Workflow className="mr-1.5 h-3.5 w-3.5" />Execution Map
                </Button>
              </Link>
            )}
            <Link href={`/repos/${repoId}/chat`}>
              <Button variant="ghost" size="sm" className="text-xs h-7">
                <ArrowRight className="mr-1.5 h-3.5 w-3.5" />Ask Repo
              </Button>
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MetricCard helper
// ---------------------------------------------------------------------------

function MetricCard({ label, value, icon, color }: {
  label: string; value: string | number; icon: React.ReactNode; color: string;
}) {
  const colorMap: Record<string, string> = {
    indigo:  "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
    orange:  "text-orange-400 bg-orange-500/10 border-orange-500/20",
    violet:  "text-violet-400 bg-violet-500/10 border-violet-500/20",
    rose:    "text-rose-400 bg-rose-500/10 border-rose-500/20",
    amber:   "text-amber-400 bg-amber-500/10 border-amber-500/20",
    emerald: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    slate:   "text-slate-400 bg-slate-500/10 border-slate-500/20",
  };
  return (
    <div className={cn("rounded-xl border px-3 py-3 flex flex-col gap-1", colorMap[color] || colorMap.slate)}>
      <div className="flex items-center gap-1.5 text-current opacity-70">
        {icon}<span className="text-[10px] font-semibold uppercase tracking-widest">{label}</span>
      </div>
      <div className="text-lg font-bold text-white">{value}</div>
    </div>
  );
}
