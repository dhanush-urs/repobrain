"use client";

import { useEffect, useMemo, useState } from "react";
import { PollingStatus } from "@/components/refresh/PollingStatus";
import { RefreshJobStatusBadge } from "@/components/refresh/RefreshJobStatusBadge";
import { getRefreshJob } from "@/lib/api";
import type { RefreshJob } from "@/lib/types";
import { Clock, GitBranch, Tag, FileCode, AlertCircle, Fingerprint, Activity } from "lucide-react";

type Props = {
  initialJob: RefreshJob;
};

function ClientOnlyDate({ date }: { date: string }) {
  const [formatted, setFormatted] = useState<string>("");
  useEffect(() => {
    setFormatted(
      new Date(date).toLocaleString([], {
        hour: "2-digit",
        minute: "2-digit",
        month: "short",
        day: "numeric",
      })
    );
  }, [date]);
  return <>{formatted || "…"}</>;
}

export function RefreshJobDetail({ initialJob }: Props) {
  const [job, setJob] = useState<RefreshJob>(initialJob);

  const active = useMemo(() =>
    ["queued", "processing", "refreshing", "running"].includes((job.status || "").toLowerCase()),
    [job.status]
  );

  useEffect(() => {
    if (!active) return;
    const id = setInterval(async () => {
      try {
        const latest = await getRefreshJob(job.id);
        if (latest) setJob(latest);
      } catch { /* ignore */ }
    }, 3000);
    return () => clearInterval(id);
  }, [job.id, active]);

  return (
    <div className="divide-y divide-white/5">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between px-5 py-3.5 bg-white/[0.01]">
        <div className="flex items-center gap-3">
          <div className="rounded bg-slate-900 p-2 text-indigo-400 border border-white/5 shadow-inner">
            <Activity size={16} />
          </div>
          <div>
            <h3 className="text-[11px] font-bold text-slate-200 uppercase tracking-wider">Job Detail</h3>
            <PollingStatus active={active} />
          </div>
        </div>
        <RefreshJobStatusBadge status={job.status} />
      </div>

      <div className="px-6 py-6 space-y-6">
        {/* Summary + metadata */}
        <div className="grid gap-6 md:grid-cols-3">
          <div className="md:col-span-2 space-y-5">
            {job.summary && (
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600 mb-1.5">Event Summary</div>
                <p className="text-[13px] text-slate-300 leading-relaxed font-medium">{job.summary}</p>
              </div>
            )}

            <div className="grid gap-2 sm:grid-cols-2">
              <MetaCell icon={<Tag size={12} />} label="Event" value={job.event_type} />
              <MetaCell icon={<Fingerprint size={12} />} label="Origin" value={job.trigger_source} />
              <MetaCell icon={<GitBranch size={12} />} label="Context" value={job.branch || "main"} />
              <MetaCell icon={<Clock size={12} />} label="Logged At" value={<ClientOnlyDate date={job.created_at} />} />
            </div>
          </div>

          {/* IDs */}
          <div className="space-y-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Identifiers</div>
            <div className="rounded border border-white/5 bg-slate-950/40 p-4 space-y-4 shadow-inner">
              <div>
                <div className="text-[9px] text-slate-700 mb-1.5 uppercase font-bold tracking-wider">Job Reference</div>
                <div className="font-mono text-[10px] text-indigo-400/80 p-2 bg-slate-900/50 rounded border border-white/5 break-all select-all">{job.id}</div>
              </div>
              <div>
                <div className="text-[9px] text-slate-700 mb-1.5 uppercase font-bold tracking-wider">Repository Hash</div>
                <div className="font-mono text-[10px] text-slate-600 p-2 bg-slate-900/50 rounded border border-white/5 break-all select-all">{job.repository_id}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Error */}
        {job.error_message && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <AlertCircle size={12} className="text-rose-500/80" />
              <span className="text-[10px] font-bold text-rose-500/80 uppercase tracking-wider">System Exception</span>
            </div>
            <div className="rounded border border-rose-500/20 bg-rose-500/5 p-4">
              <pre className="font-mono text-[11px] text-rose-400/90 overflow-x-auto leading-relaxed whitespace-pre-wrap">{job.error_message}</pre>
            </div>
          </div>
        )}

        {/* Changed files */}
        <div className="space-y-2.5">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <FileCode size={12} className="text-indigo-500/60" />
              <span className="text-[10px] font-bold text-slate-200 uppercase tracking-wider">Affected Artifacts</span>
            </div>
            <span className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">{job.changed_files.length} Total</span>
          </div>

          <div className="rounded border border-border/40 bg-slate-950/40 shadow-inner overflow-hidden">
            {job.changed_files.length ? (
              <div className="divide-y divide-white/[0.04]">
                {job.changed_files.map((file, i) => (
                  <div key={`${file}-${i}`} className="flex items-center gap-3 px-4 py-2 text-[11px] text-slate-500 hover:text-slate-200 hover:bg-white/[0.01] transition-colors border-b border-white/[0.02] last:border-0">
                    <div className="h-1 w-1 rounded-full bg-slate-700 shrink-0" />
                    <span className="font-mono truncate">{file}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-8 text-center text-sm text-slate-600 italic">No files changed in this event.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MetaCell({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded border border-white/5 bg-white/[0.01] px-3.5 py-2.5">
      <span className="text-slate-700 shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="text-[9px] uppercase text-slate-600 font-bold tracking-wider mb-0.5">{label}</p>
        <p className="text-[13px] text-slate-400 font-medium truncate leading-none">{value}</p>
      </div>
    </div>
  );
}
