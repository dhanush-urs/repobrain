"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import type { AskRepoResponse } from "@/lib/types";
import { Button } from "@/components/common/Button";
import { Textarea } from "@/components/common/Input";
import { Card } from "@/components/common/Card";
import { Send, Bot, User, Quote, ExternalLink, ChevronDown, ChevronUp, Sparkles } from "lucide-react";

type Props = {
  repoId: string;
};

export function AskRepoForm({ repoId }: Props) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AskRepoResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(false);
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
    setShowSources(false);

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
      if (Array.isArray(payload.citations) && payload.citations.length > 0) {
        setShowSources(true);
      }
    } catch (err) {
      if ((err as Error)?.name === "AbortError") return;
      if (requestSeq !== requestSeqRef.current) return;
      setError(err instanceof Error ? err.message : "Failed to ask repository");
    } finally {
      if (requestSeq === requestSeqRef.current) setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-8">
      {/* Input */}
      <Card className="border-indigo-500/20 bg-slate-900/40 p-0 overflow-hidden">
        <form onSubmit={onSubmit}>
          <div className="p-5">
            <Textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSubmit(e as any);
                }
              }}
              rows={3}
              className="min-h-[80px] w-full resize-none border-none bg-transparent p-0 text-base placeholder:text-slate-600 focus-visible:ring-0 text-white"
              placeholder="Ask anything about the codebase..."
            />
          </div>
          <div className="flex items-center justify-between px-5 py-3 border-t border-white/5 bg-white/[0.01]">
            <span className="text-xs text-slate-600 hidden sm:block">Shift + Enter for newline</span>
            <Button type="submit" disabled={loading || !question.trim()} isLoading={loading} variant="indigo" size="sm" className="px-5">
              <Send className="mr-2 h-3.5 w-3.5" />
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
        <div className="flex items-start gap-4 animate-in fade-in duration-300">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-600 shadow-lg shadow-indigo-500/20">
            <Bot className="h-4 w-4 text-white" />
          </div>
          <div className="pt-1.5 space-y-3">
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <span>Thinking</span>
              <div className="flex gap-1">
                <div className="h-1 w-1 rounded-full bg-indigo-400 animate-bounce [animation-delay:-0.3s]" />
                <div className="h-1 w-1 rounded-full bg-indigo-400 animate-bounce [animation-delay:-0.15s]" />
                <div className="h-1 w-1 rounded-full bg-indigo-400 animate-bounce" />
              </div>
            </div>
            <div className="space-y-2">
              <div className="h-3 w-64 animate-pulse rounded bg-white/5" />
              <div className="h-3 w-48 animate-pulse rounded bg-white/5" />
            </div>
          </div>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
          {/* Question */}
          <div className="flex items-start gap-4 opacity-70">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-800 ring-1 ring-white/10">
              <User className="h-4 w-4 text-slate-400" />
            </div>
            <div className="pt-1.5">
              <div className="text-xs text-slate-500 mb-1">You</div>
              <div className="text-sm text-slate-200">{result.question}</div>
            </div>
          </div>

          {/* Answer */}
          <div className="flex items-start gap-4">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-600 shadow-lg shadow-indigo-500/20">
              <Bot className="h-4 w-4 text-white" />
            </div>
            <div className="flex-1 space-y-4 pt-1.5">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-slate-300">RepoBrain AI</span>
                <Sparkles className="h-3 w-3 text-indigo-400" />
              </div>

              <div className="rounded-xl border border-white/5 bg-slate-950/40 px-5 py-4">
                <div className="whitespace-pre-wrap leading-7 text-slate-200 text-sm">
                  {result.answer}
                </div>
              </div>

              {/* Citations */}
              <div className="space-y-2">
                <button
                  onClick={() => setShowSources(!showSources)}
                  className="flex items-center gap-2 text-xs text-slate-500 hover:text-indigo-400 transition-colors"
                >
                  <Quote className="h-3 w-3" />
                  Sources & Citations
                  {showSources ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                </button>

                {showSources && (
                  <div className="grid gap-2 pt-1 sm:grid-cols-2 animate-in fade-in duration-300">
                    {Array.isArray(result.citations) && result.citations.length > 0 ? (
                      result.citations.map((c, i) => (
                        <CitationCard key={c.chunk_id || i} citation={c} repoId={repoId} />
                      ))
                    ) : (
                      <p className="text-xs text-slate-600 italic">No citations available.</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CitationCard({ citation, repoId }: { citation: any; repoId: string }) {
  const fileName = citation.file_path?.split("/").pop() || "unknown";
  // Only deep-link if file_id is a valid non-null, non-"null" string
  const hasValidFileId = citation.file_id && citation.file_id !== "null" && citation.file_id !== "undefined";
  const fileHref = hasValidFileId
    ? `/repos/${repoId}/files/${citation.file_id}${citation.start_line ? `?line=${citation.start_line}` : ""}`
    : null;

  const inner = (
    <div className="group rounded-xl border border-white/5 bg-white/[0.02] p-3 transition-all hover:border-indigo-500/30 hover:bg-white/[0.04]">
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-1.5 w-1.5 rounded-full bg-indigo-500/60 shrink-0" />
          <span className="truncate text-sm font-medium text-slate-300 group-hover:text-indigo-300 transition-colors">{fileName}</span>
        </div>
        <ExternalLink className="h-3 w-3 shrink-0 text-slate-600 group-hover:text-indigo-400 transition-colors" />
      </div>
      <div className="flex items-center gap-2 text-[11px] text-slate-500">
        <span className="truncate max-w-[160px]">{citation.file_path}</span>
        {citation.start_line && (
          <span className="shrink-0 rounded bg-slate-900 px-1.5 py-0.5 ring-1 ring-white/10 font-mono text-[10px] text-slate-400">
            L{citation.start_line}{citation.end_line ? `–${citation.end_line}` : ""}
          </span>
        )}
      </div>
    </div>
  );

  if (fileHref) {
    return <Link href={fileHref}>{inner}</Link>;
  }
  return <div className="cursor-default">{inner}</div>;
}
