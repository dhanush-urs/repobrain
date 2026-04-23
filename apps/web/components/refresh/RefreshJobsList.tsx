"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PollingStatus } from "@/components/refresh/PollingStatus";
import { RefreshJobStatusBadge } from "@/components/refresh/RefreshJobStatusBadge";
import { getRepositoryRefreshJobs } from "@/lib/api";
import type { RefreshJob } from "@/lib/types";
import { Button } from "@/components/common/Button";
import { ChevronRight, Clock, GitBranch, FileSpreadsheet } from "lucide-react";

type Props = {
  repoId: string;
  initialJobs: RefreshJob[];
};

export function RefreshJobsList({ repoId, initialJobs }: Props) {
  const [jobs, setJobs] = useState<RefreshJob[]>(initialJobs);

  const hasActiveJobs = useMemo(() => {
    return jobs.some((job) =>
      ["queued", "processing", "refreshing", "running"].includes(
        (job.status || "").toLowerCase()
      )
    );
  }, [jobs]);

  useEffect(() => {
    if (!hasActiveJobs) return;

    const intervalId = setInterval(async () => {
      try {
        const latest = await getRepositoryRefreshJobs(repoId);
        setJobs(latest.items);
      } catch {
        // ignore polling failures
      }
    }, 3000);

    return () => clearInterval(intervalId);
  }, [repoId, hasActiveJobs]);

  if (!jobs.length) {
    return (
      <div className="py-20 px-6 text-center text-slate-500 italic text-sm">
        No background operations recorded in history.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="px-6 py-4 border-b border-white/5 bg-white/[0.01] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="h-4 w-4 text-indigo-400" />
          <h3 className="text-xs font-bold text-white uppercase tracking-widest">Operation Queue</h3>
        </div>
        <PollingStatus active={hasActiveJobs} />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-white/5 bg-white/[0.01]">
              <th className="px-5 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Status</th>
              <th className="px-5 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest">Event</th>
              <th className="px-5 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest hidden md:table-cell">Branch</th>
              <th className="px-5 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest hidden sm:table-cell">Files</th>
              <th className="px-5 py-3 text-[10px] font-bold text-slate-500 uppercase tracking-widest">When</th>
              <th className="px-5 py-3 text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {jobs.map((job) => (
              <tr key={job.id} className="group hover:bg-white/[0.02] transition-colors">
                <td className="px-5 py-3.5">
                  <RefreshJobStatusBadge status={job.status} />
                </td>
                <td className="px-5 py-3.5">
                  <span className="rounded-md bg-indigo-500/10 px-2 py-1 text-[10px] font-bold text-indigo-400 ring-1 ring-indigo-500/20 uppercase tracking-tight">
                    {job.event_type}
                  </span>
                </td>
                <td className="px-5 py-3.5 hidden md:table-cell">
                  <div className="flex items-center gap-1.5 text-xs text-slate-400">
                    <GitBranch className="h-3 w-3 text-slate-600" />
                    <span className="truncate max-w-[120px]">{job.branch || "main"}</span>
                  </div>
                </td>
                <td className="px-5 py-3.5 hidden sm:table-cell">
                  <div className="flex items-center gap-1.5 text-xs text-slate-500">
                    <FileSpreadsheet className="h-3 w-3" />
                    <span>{job.changed_files.length} changed</span>
                  </div>
                </td>
                <td className="px-5 py-3.5">
                  <div className="text-xs text-slate-300 font-medium tabular-nums">
                    {new Date(job.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                  <div className="text-[10px] text-slate-600 tabular-nums">
                    {new Date(job.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                  </div>
                </td>
                <td className="px-5 py-3.5 text-right">
                  <Link href={`/repos/${repoId}/refresh-jobs/${job.id}`}>
                    <Button variant="ghost" size="sm" className="h-7 text-xs opacity-0 group-hover:opacity-100 transition-opacity hover:bg-indigo-500/10 hover:text-indigo-400">
                      Logs
                      <ChevronRight className="ml-1 h-3 w-3" />
                    </Button>
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
