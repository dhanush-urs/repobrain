"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ActionConsole } from "@/components/common/ActionConsole";
import { RepoStatusBadge } from "@/components/repo/RepoStatusBadge";
import { getRepository, getJobs } from "@/lib/api";
import type { Repository } from "@/lib/types";

type Props = {
  repoId: string;
  initialStatus?: string;
};

export function RepoActions({ repoId, initialStatus = "unknown" }: Props) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [repo, setRepo] = useState<Repository | null>(null);
  const [polling, setPolling] = useState(false);

  const currentStatus = repo?.status || initialStatus;

  // Compute states strictly
  const isProcessing = useMemo(() => {
    const s = (currentStatus || "").toLowerCase();
    return ["queued", "running", "parsing", "indexing", "embedding", "processing"].includes(s);
  }, [currentStatus]);

  // Polling logic
  useEffect(() => {
    let intervalId: NodeJS.Timeout | null = null;
    let isMounted = true;

    async function refreshData() {
      if (!isMounted) return;
      try {
        const latest = await getRepository(repoId);
        
        // Fetch real status text from the latest job so Action Console is truthful
        try {
          const jobsRes = await getJobs(repoId, 1);
          if (jobsRes.items && jobsRes.items.length > 0) {
            setMessage(jobsRes.items[0].message || "Processing...");
          }
        } catch {
          // ignore job fetch errors
        }

        if (latest && latest.status !== currentStatus) {
          router.refresh(); // Trigger Server Component re-render
        }
        if (latest) {
          setRepo(latest);
        }
      } catch {
        // ignore polling failures gracefully
      }
    }

    if (isProcessing) {
      setPolling(true);
      // Fetch immediately on mount if processing, and update action console
      refreshData();
      intervalId = setInterval(refreshData, 2000);
    } else {
      setPolling(false);
    }

    return () => {
      isMounted = false;
      if (intervalId) clearInterval(intervalId);
    };
  }, [repoId, isProcessing, currentStatus, router]);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-white/5 bg-slate-950/60 p-4">
        <div className="flex items-center gap-3">
          <RepoStatusBadge status={currentStatus} />
          {polling && (
            <span className="text-xs text-amber-300 animate-pulse">Syncing…</span>
          )}
        </div>
      </div>
      <ActionConsole message={message} />
    </div>
  );
}
