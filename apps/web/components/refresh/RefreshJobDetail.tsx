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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between px-6 py-4 bg-white/[0.01]">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-slate-900 p-2 text-indigo-400 ring-1 ring-indigo-500/20">
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-white">Job Detail</h3>
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
                <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">Summary</div>
                <p className="text-sm text-slate-200 leading-relaxed">{job.summary}</p>
              </div>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
              <MetaCell icon={<Tag size={14} />} label="Event Type" value={job.event_type} />
              <MetaCell icon={<Fingerprint size={14} />} label="Trigger" value={job.trigger_source} />
              <MetaCell icon={<GitBranch size={14} />} label="Branch" value={job.branch || "main"} />
              <MetaCell icon={<Clock size={14} />} label="Timestamp" value={<ClientOnlyDate date={job.created_at} />} />
            </div>
          </div>

          {/* IDs */}
          <div className="space-y-3">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">IDs</div>
            <div className="rounded-xl border border-white/5 bg-slate-950/40 p-4 space-y-3">
              <div>
                <div className="text-[9px] text-slate-600 mb-1 uppercase font-semibold tracking-widest">Job ID</div>
                <div className="font-mono text-[10px] text-indigo-400/70 p-2 bg-slate-900 rounded border border-white/5 break-all">{job.id}</div>
              </div>
              <div>
                <div className="text-[9px] text-slate-600 mb-1 uppercase font-semibold tracking-widest">Repository ID</div>
                <div className="font-mono text-[10px] text-slate-500 p-2 bg-slate-900 rounded border border-white/5 break-all">{job.repository_id}</div>
              </div>
            </div>
          </div>
        </div>

        {/* Error */}
        {job.error_message && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <AlertCircle size={13} className="text-rose-500" />
              <span className="text-[10px] font-semibold text-rose-500 uppercase tracking-widest">Error</span>
            </div>
            <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4">
              <pre className="font-mono text-xs text-rose-400 overflow-x-auto leading-relaxed whitespace-pre-wrap">{job.error_message}</pre>
            </div>
          </div>
        )}

        {/* Changed files */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileCode size={13} className="text-indigo-400" />
              <span className="text-[10px] font-semibold text-white uppercase tracking-widest">Changed Files</span>
            </div>
            <span className="text-[10px] text-slate-500">{job.changed_files.length} files</span>
          </div>

          <div className="rounded-xl border border-white/5 bg-slate-950/40 p-1">
            {job.changed_files.length ? (
              <div className="divide-y divide-white/[0.04]">
                {job.changed_files.map((file, i) => (
                  <div key={`${file}-${i}`} className="flex items-center gap-3 px-4 py-2.5 text-xs text-slate-400 hover:text-white hover:bg-white/[0.02] transition-colors rounded-lg">
                    <div className="h-1.5 w-1.5 rounded-full bg-slate-700 shrink-0" />
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
    <div className="flex items-center gap-3 rounded-lg bg-slate-950/40 border border-white/5 px-4 py-3">
      <span className="text-slate-500 shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="text-[9px] uppercase text-slate-500 font-semibold tracking-widest mb-0.5">{label}</p>
        <p className="text-sm text-slate-200 font-medium truncate">{value}</p>
      </div>
    </div>
  );
}
