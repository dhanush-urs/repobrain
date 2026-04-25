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
    <div className="space-y-4">
      <div className="px-5 py-3 border-b border-white/5 bg-white/[0.01] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock size={14} className="text-indigo-400" />
          <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Operational Queue</h3>
        </div>
        <PollingStatus active={hasActiveJobs} />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-white/5 bg-white/[0.01]">
              <th className="px-5 py-2.5 text-[9px] font-bold text-slate-600 uppercase tracking-wider">Status</th>
              <th className="px-5 py-2.5 text-[9px] font-bold text-slate-600 uppercase tracking-wider">Event</th>
              <th className="px-5 py-2.5 text-[9px] font-bold text-slate-600 uppercase tracking-wider hidden md:table-cell">Branch</th>
              <th className="px-5 py-2.5 text-[9px] font-bold text-slate-600 uppercase tracking-wider hidden sm:table-cell">Files</th>
              <th className="px-5 py-2.5 text-[9px] font-bold text-slate-600 uppercase tracking-wider">Timestamp</th>
              <th className="px-5 py-2.5 text-right"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.02]">
            {jobs.map((job) => (
              <tr key={job.id} className="group hover:bg-white/[0.01] transition-colors">
                <td className="px-5 py-2.5">
                  <RefreshJobStatusBadge status={job.status} />
                </td>
                <td className="px-5 py-2.5">
                  <span className="rounded border border-indigo-500/20 bg-indigo-500/5 px-1.5 py-0.5 text-[9px] font-bold text-indigo-400 uppercase tracking-wider">
                    {job.event_type}
                  </span>
                </td>
                <td className="px-5 py-2.5 hidden md:table-cell">
                  <div className="flex items-center gap-1.5 text-[11px] text-slate-500">
                    <GitBranch size={11} className="text-slate-700" />
                    <span className="truncate max-w-[120px] font-mono">{job.branch || "main"}</span>
                  </div>
                </td>
                <td className="px-5 py-2.5 hidden sm:table-cell">
                  <div className="flex items-center gap-1.5 text-[11px] text-slate-600">
                    <FileSpreadsheet size={11} />
                    <span>{job.changed_files.length} changed</span>
                  </div>
                </td>
                <td className="px-5 py-2.5">
                  <div className="text-[11px] text-slate-400 font-medium tabular-nums">
                    {new Date(job.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                  <div className="text-[9px] text-slate-700 font-medium tabular-nums uppercase">
                    {new Date(job.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                  </div>
                </td>
                <td className="px-5 py-2.5 text-right">
                  <Link href={`/repos/${repoId}/refresh-jobs/${job.id}`}>
                    <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity hover:bg-indigo-500/10 hover:text-indigo-400">
                      Details
                      <ChevronRight size={10} className="ml-1" />
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
