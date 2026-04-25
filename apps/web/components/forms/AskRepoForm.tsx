"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import type { AskRepoResponse } from "@/lib/types";
import { Button } from "@/components/common/Button";
import { Textarea } from "@/components/common/Input";
import { Card } from "@/components/common/Card";
import {
  Send, Bot, User, Quote, ExternalLink, ChevronDown,
  FileCode, GitBranch, Workflow, Info
} from "lucide-react";
import { cn } from "@/lib/utils";

type Props = { repoId: string };

// ---------------------------------------------------------------------------
// Analyst console — structured answer rendering
// ---------------------------------------------------------------------------

const SECTION_KIND_LABELS: Record<string, string> = {
  summary:      "Summary",
  stack:        "Stack & Framework",
  architecture: "Architecture",
  capabilities: "Capabilities",
  flow:         "Execution Flow",
  files:        "Key Files",
  risks:        "Risks & Notes",
  notes:        "Notes",
  symbol:       "Symbol",
  usage:        "Usage",
  impact:       "Impact",
  evidence:     "Evidence",
};

function AnalystAnswer({ result, repoId }: { result: AskRepoResponse; repoId: string }) {
  const [openSections, setOpenSections] = useState<Set<string>>(new Set());
  const [showEvidence, setShowEvidence] = useState(false);
  const [showSources, setShowSources] = useState(false);

  const sa = result.structured_answer;
  const conf = result.answer_confidence;
  const eb = result.evidence_breakdown;

  function toggleSection(key: string) {
    setOpenSections(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }

  // Determine if section is open: default_open OR manually toggled
  function isSectionOpen(key: string, defaultOpen?: boolean) {
    if (openSections.has(key + "_force_closed")) return false;
    if (openSections.has(key)) return true;
    return defaultOpen ?? false;
  }

  // Evidence breakdown strip
  const evidenceStrip = eb ? [
    eb.exact_edges_used > 0 && `${eb.exact_edges_used} exact`,
    eb.symbol_hits_used > 0 && `${eb.symbol_hits_used} symbol`,
    eb.inferred_edges_used > 0 && `${eb.inferred_edges_used} inferred`,
    eb.semantic_hits_used > 0 && `${eb.semantic_hits_used} semantic`,
  ].filter(Boolean).join(" · ") : null;

  // If no structured answer, fall back to plain answer card
  if (!sa || !sa.sections?.length) {
    return (
      <div className="space-y-3">
        <div className="rounded-lg border border-border/40 bg-slate-900/40 px-4 py-3.5">
          <div className="whitespace-pre-wrap leading-7 text-slate-200 text-sm">{result.answer}</div>
        </div>
        <ConfidenceRow conf={conf} strip={evidenceStrip} />
        <WhyThisAnswer breakdown={eb} confidence={conf} />
        <CitationsRow result={result} repoId={repoId} showSources={showSources} setShowSources={setShowSources} />
      </div>
    );
  }

  const primarySection = sa.sections.find(s => s.key === "summary" || s.priority === 0);
  const otherSections = sa.sections.filter(s => s !== primarySection && s.key !== "confidence_note");
  const noteSection = sa.sections.find(s => s.key === "confidence_note");

  return (
    <div className="space-y-3">
      {/* ── Primary answer card ── */}
      <div className="rounded-lg border border-border/40 bg-slate-900/40 px-4 py-3.5 space-y-2">
        <div className="text-[9px] font-bold uppercase tracking-[0.15em] text-slate-600">
          RepoBrain Analysis
        </div>
        <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
          {primarySection?.content || sa.summary || result.answer}
        </div>
        <ConfidenceRow conf={conf} strip={evidenceStrip} />
      </div>

      {/* ── Structured sections ── */}
      {otherSections.length > 0 && (
        <div className="space-y-1.5">
          {otherSections.map(section => {
            const isOpen = isSectionOpen(section.key, section.default_open);
            const label = SECTION_KIND_LABELS[section.kind] || section.title;
            if (!section.collapsible) {
              return (
                <div key={section.key} className="rounded-lg border border-white/5 bg-slate-900/30 px-4 py-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">{label}</div>
                  <div className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{section.content}</div>
                </div>
              );
            }
            return (
              <div key={section.key} className="rounded-lg border border-white/5 bg-slate-900/20 overflow-hidden">
                <button
                  onClick={() => toggleSection(section.key)}
                  className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-white/[0.02] transition-colors"
                >
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
                  <ChevronDown size={12} className={cn("text-slate-600 transition-transform shrink-0", isOpen && "rotate-180")} />
                </button>
                {isOpen && (
                  <div className="px-4 pb-3 text-sm text-slate-300 leading-relaxed whitespace-pre-wrap border-t border-white/5 pt-2.5">
                    {section.content}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Key files ── */}
      {sa.key_files && sa.key_files.length > 0 && (
        <div className="rounded-lg border border-white/5 bg-slate-900/20 overflow-hidden">
          <button
            onClick={() => toggleSection("key_files")}
            className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-white/[0.02] transition-colors"
          >
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Key Files</span>
            <ChevronDown size={12} className={cn("text-slate-600 transition-transform shrink-0", isSectionOpen("key_files", true) && "rotate-180")} />
          </button>
          {isSectionOpen("key_files", true) && (
            <div className="border-t border-white/5 divide-y divide-white/[0.03]">
              {sa.key_files.slice(0, 6).map((kf, i) => {
                const fname = kf.path.split("/").pop() || kf.path;
                return (
                  <div key={i} className="flex items-center gap-3 px-4 py-2 group">
                    <FileCode size={12} className="text-slate-600 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <span className="text-xs font-mono text-slate-300 truncate block">{fname}</span>
                      {kf.reason && <span className="text-[10px] text-slate-600">{kf.reason.replace(/_/g, " ")}</span>}
                    </div>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <Link href={`/repos/${repoId}/graph?view=files`} title="Graph">
                        <button className="p-1 text-slate-600 hover:text-cyan-400 transition-colors"><GitBranch size={11} /></button>
                      </Link>
                      <Link href={`/repos/${repoId}/flows?mode=file&query=${encodeURIComponent(kf.path)}`} title="Flow">
                        <button className="p-1 text-slate-600 hover:text-violet-400 transition-colors"><Workflow size={11} /></button>
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Confidence note ── */}
      {noteSection && (
        <div className="flex items-start gap-2 rounded-lg border border-slate-700/30 bg-slate-800/20 px-3 py-2">
          <Info size={12} className="text-slate-600 shrink-0 mt-0.5" />
          <p className="text-[11px] text-slate-500">{noteSection.content}</p>
        </div>
      )}

      {/* ── Why this answer? ── */}
      <WhyThisAnswer breakdown={eb} confidence={conf} />

      {/* ── Supporting evidence (collapsible, raw snippets here only) ── */}
      {sa.evidence_preview && sa.evidence_preview.length > 0 && (
        <div>
          <button
            onClick={() => setShowEvidence(v => !v)}
            className="flex items-center gap-1.5 text-[10px] text-slate-600 hover:text-slate-400 transition-colors"
          >
            <ChevronDown size={11} className={cn("transition-transform", showEvidence && "rotate-180")} />
            Supporting evidence ({sa.evidence_preview.length})
          </button>
          {showEvidence && (
            <div className="mt-2 space-y-2 animate-in fade-in duration-200">
              {sa.evidence_preview.map((ev, i) => (
                <div key={i} className="rounded-lg border border-white/5 bg-slate-950/40 px-3 py-2">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-[10px] font-mono text-slate-500 truncate">{ev.file_path}</span>
                    {ev.line_start && <span className="text-[9px] text-slate-700 shrink-0">L{ev.line_start}{ev.line_end ? `–${ev.line_end}` : ""}</span>}
                    {ev.label && <span className="text-[9px] text-slate-700 shrink-0 uppercase tracking-wider">{ev.label}</span>}
                  </div>
                  {ev.snippet && (
                    <pre className="text-[11px] text-slate-400 font-mono whitespace-pre-wrap overflow-hidden leading-relaxed max-h-24 overflow-y-auto">
                      {ev.snippet}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Citations ── */}
      <CitationsRow result={result} repoId={repoId} showSources={showSources} setShowSources={setShowSources} />
    </div>
  );
}

function ConfidenceRow({ conf, strip }: { conf?: string | null; strip?: string | null }) {
  if (!conf) return null;
  return (
    <div className="flex items-center gap-2 flex-wrap pt-1">
      <span className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold",
        conf === "high" ? "text-emerald-400 border-emerald-500/20 bg-emerald-500/5"
          : conf === "medium" ? "text-amber-400 border-amber-500/20 bg-amber-500/5"
          : "text-slate-500 border-slate-500/20 bg-slate-500/5"
      )}>
        {conf === "high" ? "High confidence" : conf === "medium" ? "Medium confidence" : "Low confidence"}
      </span>
      {strip && <span className="text-[10px] text-slate-600">{strip}</span>}
    </div>
  );
}

function WhyThisAnswer({ breakdown, confidence }: {
  breakdown?: AskRepoResponse["evidence_breakdown"];
  confidence?: string | null;
}) {
  const [open, setOpen] = useState(false);
  if (!breakdown) return null;

  const parts: string[] = [];
  if (breakdown.exact_edges_used > 0) parts.push(`${breakdown.exact_edges_used} exact match${breakdown.exact_edges_used !== 1 ? "es" : ""}`);
  if (breakdown.symbol_hits_used > 0) parts.push(`${breakdown.symbol_hits_used} symbol hit${breakdown.symbol_hits_used !== 1 ? "s" : ""}`);
  if (breakdown.inferred_edges_used > 0) parts.push(`${breakdown.inferred_edges_used} inferred edge${breakdown.inferred_edges_used !== 1 ? "s" : ""}`);
  if (breakdown.semantic_hits_used > 0) parts.push(`${breakdown.semantic_hits_used} semantic snippet${breakdown.semantic_hits_used !== 1 ? "s" : ""}`);

  const summary = parts.length > 0 ? parts.join(", ") : "semantic retrieval only";
  const isWeak = confidence === "low" || (breakdown.exact_edges_used === 0 && breakdown.symbol_hits_used === 0);

  return (
    <div>
      <button onClick={() => setOpen(v => !v)} className="flex items-center gap-1.5 text-[10px] text-slate-600 hover:text-slate-400 transition-colors">
        <ChevronDown size={11} className={cn("transition-transform", open && "rotate-180")} />
        Why this answer?
      </button>
      {open && (
        <div className="mt-1.5 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2 space-y-1 animate-in fade-in duration-200">
          <p className="text-[11px] text-slate-400">Built from: <span className="text-slate-300">{summary}</span></p>
          {isWeak && <p className="text-[11px] text-slate-600">No exact symbol or graph match — relies on semantic similarity. Re-index for stronger evidence.</p>}
          {breakdown.exact_edges_used > 0 && <p className="text-[11px] text-slate-500">Exact matches include symbol definitions or direct graph edges — high reliability.</p>}
          {breakdown.inferred_edges_used > 0 && breakdown.exact_edges_used === 0 && <p className="text-[11px] text-slate-600">Evidence includes inferred edges — moderate reliability.</p>}
        </div>
      )}
    </div>
  );
}

function CitationsRow({ result, repoId, showSources, setShowSources }: {
  result: AskRepoResponse;
  repoId: string;
  showSources: boolean;
  setShowSources: (v: boolean) => void;
}) {
  return (
    <div className="space-y-2">
      <button
        onClick={() => setShowSources(!showSources)}
        className="flex items-center gap-2 text-[10px] font-semibold text-slate-500 hover:text-slate-300 transition-colors uppercase tracking-wider"
      >
        <Quote size={11} />
        Sources & Citations
        <ChevronDown size={11} className={cn("transition-transform", showSources && "rotate-180")} />
      </button>
      {showSources && (
        <div className="grid gap-2 pt-1 sm:grid-cols-2 animate-in fade-in duration-300">
          {Array.isArray(result.citations) && result.citations.length > 0 ? (
            result.citations.map((c, i) => <CitationCard key={c.chunk_id || i} citation={c} repoId={repoId} />)
          ) : (
            <p className="text-[10px] text-slate-600 italic">No citations available.</p>
          )}
        </div>
      )}
    </div>
  );
}

function CitationCard({ citation, repoId }: { citation: any; repoId: string }) {
  const fileName = citation.file_path?.split("/").pop() || "unknown";
  const hasValidFileId = citation.file_id && citation.file_id !== "null" && citation.file_id !== "undefined";
  const fileHref = hasValidFileId
    ? `/repos/${repoId}/files/${citation.file_id}${citation.start_line ? `?line=${citation.start_line}` : ""}`
    : null;
  const inner = (
    <div className="group rounded-lg border border-white/5 bg-white/[0.02] p-2.5 transition-all hover:border-indigo-500/30 hover:bg-white/[0.04]">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-1 w-1 rounded-full bg-indigo-500/40 shrink-0" />
          <span className="truncate text-xs font-medium text-slate-400 group-hover:text-indigo-300 transition-colors">{fileName}</span>
        </div>
        <ExternalLink size={11} className="shrink-0 text-slate-600 group-hover:text-indigo-400 transition-colors" />
      </div>
      <div className="flex items-center gap-2 text-[10px] text-slate-600">
        <span className="truncate max-w-[140px] font-mono">{citation.file_path}</span>
        {citation.start_line && (
          <span className="shrink-0 rounded bg-slate-900 px-1 py-0.5 border border-white/5 font-mono text-[9px] text-slate-500">
            L{citation.start_line}{citation.end_line ? `–${citation.end_line}` : ""}
          </span>
        )}
      </div>
    </div>
  );
  if (fileHref) return <Link href={fileHref}>{inner}</Link>;
  return <div className="cursor-default">{inner}</div>;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function AskRepoForm({ repoId }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskRepoResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestSeqRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const currentQuestion = question.trim();
    if (!currentQuestion) return;

    requestSeqRef.current += 1;
    const requestSeq = requestSeqRef.current;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(`/api/v1/repos/${encodeURIComponent(repoId)}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: currentQuestion, top_k: 8 }),
        signal: controller.signal,
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const detail = (payload?.detail && typeof payload.detail === "string" ? payload.detail : null) || "Failed to get a response.";
        throw new Error(detail);
      }

      const payload = (await response.json()) as AskRepoResponse;
      if (requestSeq !== requestSeqRef.current) return;

      const cleanAnswer = (payload?.answer || "").trim();
      if (!cleanAnswer) throw new Error("No answer was generated for this query.");

      setResult({ ...payload, question: currentQuestion, answer: cleanAnswer });
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      if (requestSeq !== requestSeqRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to ask repository");
    } finally {
      if (requestSeq === requestSeqRef.current) setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      {/* Input */}
      <Card className="border-border/50 bg-slate-900/40 p-0 overflow-hidden">
        <form onSubmit={onSubmit}>
          <div className="p-4">
            <Textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(e as any); }
              }}
              rows={3}
              className="min-h-[80px] w-full resize-none border-none bg-transparent p-0 text-sm placeholder:text-slate-600 focus-visible:ring-0 text-white leading-relaxed"
              placeholder="Ask anything about the codebase..."
            />
          </div>
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/5 bg-white/[0.01]">
            <span className="text-[10px] text-slate-600 hidden sm:block uppercase tracking-wider font-medium">Shift + Enter for newline</span>
            <Button type="submit" disabled={loading || !question.trim()} isLoading={loading} variant="primary" size="sm" className="px-4">
              <Send size={14} className="mr-2" />
              Ask
            </Button>
          </div>
        </form>
      </Card>

      {error && (
        <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 text-sm text-rose-400 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-rose-500/50 hover:text-rose-400 ml-4">✕</button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-start gap-3 animate-in fade-in duration-300">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
            <Bot size={16} />
          </div>
          <div className="pt-1 space-y-2.5">
            <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500 uppercase tracking-wider">
              <span>Analyzing</span>
              <div className="flex gap-0.5">
                <div className="h-0.5 w-0.5 rounded-full bg-indigo-400 animate-pulse" />
                <div className="h-0.5 w-0.5 rounded-full bg-indigo-400 animate-pulse [animation-delay:0.2s]" />
                <div className="h-0.5 w-0.5 rounded-full bg-indigo-400 animate-pulse [animation-delay:0.4s]" />
              </div>
            </div>
            <div className="space-y-1.5">
              <div className="h-2 w-48 animate-pulse rounded-sm bg-white/5" />
              <div className="h-2 w-32 animate-pulse rounded-sm bg-white/5" />
            </div>
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
          {/* Question echo */}
          <div className="flex items-start gap-3 opacity-60">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-800 border border-white/5">
              <User size={16} className="text-slate-500" />
            </div>
            <div className="pt-1">
              <div className="text-[10px] font-semibold text-slate-500 mb-1 uppercase tracking-wider">You</div>
              <div className="text-sm text-slate-300 leading-relaxed">{result.question}</div>
            </div>
          </div>

          {/* Analyst answer */}
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Bot size={16} />
            </div>
            <div className="flex-1 pt-1">
              <AnalystAnswer result={result} repoId={repoId} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
