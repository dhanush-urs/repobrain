"use client";

import { AskRepoResponse } from "@/lib/types";
import Link from "next/link";
import { 
  Terminal, 
  ShieldAlert, 
  Info, 
  Layers, 
  Code2, 
  Zap, 
  FileCode,
  AlertTriangle,
  History,
  Activity
} from "lucide-react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type Props = {
  result: AskRepoResponse;
  repoId: string;
};

/**
 * Refined markdown cleaner that preserves structural elements
 * like bullets and bolding for the UI to render.
 */
function formatContent(text: string) {
  if (!text) return "";
  return text
    .replace(/^[=\-]{3,}$/gm, "") // Remove old separator lines
    .replace(/^•\s+/gm, "- ")     // Normalize bullets
    .trim();
}

export function AskRepoPanel({ result, repoId }: Props) {
  const mode = result.answer_mode || "general";
  const confidence = result.confidence?.toLowerCase() || "medium";
  
  // Parse structured sections from markdown
  // We look for '### Section Name' or 'Section Name:'
  const sections: { title: string; body: string }[] = [];
  const rawAnswer = result.answer || "";
  
  const parts = rawAnswer.split(/(?:^|\n)###\s+(?:\d+\.\s+)?/);
  for (const part of parts) {
    if (!part.trim()) continue;
    const lines = part.split("\n");
    const title = lines[0].trim().replace(/:$/, "");
    const body = formatContent(lines.slice(1).join("\n"));
    
    // Skip noisy meta-sections that are redundant or already handled in the UI
    const skipTitles = ["Confidence", "Evidence", "Query Type", "Evidence Verification", "Confidence Justification", "Evidence Checklist"];
    if (!skipTitles.some(t => title.includes(t)) && body) {
      sections.push({ title, body });
    }
  }

  // Fallback if no ### sections were found
  if (sections.length === 0 && rawAnswer) {
    sections.push({ title: "Analysis", body: formatContent(rawAnswer) });
  }

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-500">
      {/* Precision Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div className="flex items-center gap-3">
          <div className={cn(
            "p-2 rounded-lg bg-slate-800 border",
            mode === 'impact' ? "border-amber-500/50 text-amber-400" :
            mode === 'code' ? "border-blue-500/50 text-blue-400" :
            "border-indigo-500/50 text-indigo-400"
          )}>
            {mode === 'impact' ? <ShieldAlert size={18} /> :
             mode === 'code' ? <Code2 size={18} /> :
             <Layers size={18} />}
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-200 capitalize">
              {mode} Intelligence Mode
            </h3>
            <p className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">
              Intent: {result.query_type?.replace(/_/g, " ") || "Semantic QA"}
            </p>
          </div>
        </div>

        <div className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-full border text-[10px] font-bold uppercase tracking-wider",
          confidence === 'high' ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400" :
          confidence === 'medium' ? "bg-amber-500/10 border-amber-500/30 text-amber-400" :
          "bg-rose-500/10 border-rose-500/30 text-rose-400"
        )}>
           <div className={cn("w-1.5 h-1.5 rounded-full", 
             confidence === 'high' ? "bg-emerald-500" : 
             confidence === 'medium' ? "bg-amber-500" : "bg-rose-500"
           )} />
           {confidence} Confidence
        </div>
      </div>

      {/* Target Resolution Block (for Code/Impact) */}
      {(mode === 'impact' || mode === 'code') && result.resolved_file && (
        <div className="rounded-xl border border-blue-500/20 bg-blue-950/20 p-4">
          <h4 className="mb-3 text-[10px] font-bold uppercase tracking-[0.2em] text-blue-400/80 flex items-center gap-2">
            <Zap size={12} className="text-blue-400" />
            Target Resolution
          </h4>
          <div className="font-mono text-sm space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-slate-500 italic shrink-0 underline decoration-slate-700">File:</span> 
              <span className="text-blue-300 truncate">{result.resolved_file}</span>
            </div>
            {result.resolved_line_number && (
              <div className="flex items-start gap-2">
                <span className="text-slate-500 italic shrink-0 underline decoration-slate-700">Line {result.resolved_line_number}:</span>
                <span className="bg-slate-900/80 px-2 py-0.5 rounded text-blue-100 border border-slate-700/50 break-all">
                  {result.matched_line?.trim() || "..."}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Main Analysis Grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          {sections.map((sec, idx) => (
            <div key={idx} className="group rounded-xl border border-slate-700/50 bg-slate-900/40 overflow-hidden shadow-lg hover:border-slate-600/50 transition-colors">
              <div className="border-b border-slate-800/80 bg-slate-900/60 px-5 py-3 flex items-center justify-between">
                <h4 className="text-[11px] font-bold uppercase tracking-widest text-slate-400 group-hover:text-slate-200 transition-colors">
                  {sec.title}
                </h4>
                <div className="w-1.5 h-1.5 rounded-full bg-indigo-500/30 group-hover:bg-indigo-500/60 transition-colors" />
              </div>
              <div className="p-6">
                <div className="text-sm text-slate-300 leading-relaxed whitespace-pre-line prose prose-invert max-w-none prose-sm">
                   {/* We use a simple bold/code parser here since no react-markdown */}
                   {(sec.body || "").split(/(\*\*.*?\*\*|`.*?`)/).map((part, i) => {
                     if (!part) return null;
                     if (part.startsWith('**') && part.endsWith('**')) {
                       return <strong key={i} className="text-indigo-200 font-bold">{part.slice(2, -2)}</strong>;
                     }
                     if (part.startsWith('`') && part.endsWith('`')) {
                       return <code key={i} className="bg-slate-800 text-blue-300 px-1.5 py-0.5 rounded text-[0.85em] font-mono border border-slate-700">{part.slice(1, -1)}</code>;
                     }
                     return part;
                   })}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Sidebar Context */}
        <div className="space-y-4">
          {/* Notes / Resolution Steps */}
          {result.notes && result.notes.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 shadow-inner">
              <h4 className="mb-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-2">
                <Activity size={12} />
                Resolution Trace
              </h4>
              <ul className="space-y-3">
                {result.notes.map((note, idx) => (
                  <li key={idx} className="text-[11px] text-slate-400 flex items-start gap-2 leading-tight">
                    <span className="w-1 h-1 rounded-full bg-slate-600 mt-1.5 shrink-0" />
                    {note}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Evidence Citations */}
          {result.citations && result.citations.length > 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
              <h4 className="mb-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 flex items-center gap-2">
                <Info size={12} />
                Source Evidence
              </h4>
              <div className="space-y-2.5">
                {result.citations.slice(0, 5).map((cit, idx) => {
                  const firstMatchLine = cit.matched_lines && cit.matched_lines.length > 0 ? cit.matched_lines[0] : cit.start_line;
                  const isExact = cit.match_type === "exact";

                  return (
                    <Link
                      key={cit.chunk_id || idx}
                      href={`/repos/${repoId}/files/${cit.file_id}${firstMatchLine ? `?line=${firstMatchLine}` : ""}`}
                      className={`group flex items-center justify-between rounded-lg border p-2 text-xs transition-colors ${
                        isExact 
                          ? "border-indigo-500/40 bg-indigo-500/5 hover:bg-indigo-500/10" 
                          : "border-slate-800 bg-slate-900/50 hover:bg-slate-800"
                      }`}
                    >
                      <div className="flex items-center gap-2 overflow-hidden">
                        <span className={`font-mono text-[10px] ${isExact ? "text-indigo-400" : "text-slate-500"}`}>
                          {idx + 1}
                        </span>
                        <span className="truncate text-slate-300 group-hover:text-white">
                          {cit.file_path}
                        </span>
                        {isExact && (
                          <span className="rounded bg-indigo-500/20 px-1 py-0.5 text-[9px] font-bold uppercase tracking-wider text-indigo-400">
                            Exact
                          </span>
                        )}
                      </div>
                      <span className="text-slate-500 group-hover:text-slate-300">
                        {cit.start_line ?? "?"}-{cit.end_line ?? "?"}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
