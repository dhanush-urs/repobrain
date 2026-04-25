import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { RefreshJobsList } from "@/components/refresh/RefreshJobsList";
import { RepoStatusPanel } from "@/components/repo/RepoStatusPanel";
import { getRepository, getRepositoryRefreshJobs } from "@/lib/api";
import { Card } from "@/components/common/Card";
import { Activity, History, AlertCircle } from "lucide-react";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RefreshJobsPage({ params }: Props) {
  const { repoId } = await params;

  const [repo, jobsData] = await Promise.all([
    getRepository(repoId).catch(() => null),
    getRepositoryRefreshJobs(repoId).catch(() => ({ items: [], total: 0 })),
  ]);

  if (!repo) {
    return (
      <div className="space-y-8 pb-16">
        <PageHeader title="Refresh Jobs" subtitle="Unable to load repository." className="mb-0" />
        <Card className="flex flex-col items-center justify-center py-16 text-center border-dashed border-white/10 bg-transparent">
          <AlertCircle className="h-8 w-8 text-rose-500 mb-3" />
          <h3 className="text-base font-semibold text-white mb-1">Repository Not Found</h3>
          <p className="text-sm text-slate-400 max-w-xs">The repository ID may be invalid or it may have been deleted.</p>
        </Card>
      </div>
    );
  }

  const hasJobs = jobsData?.items?.length > 0;

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        title="Refresh Jobs"
        subtitle="Background synchronization, parsing, and re-indexing history."
        className="mb-0"
      />

      <RepoSubnav repoId={repoId} />

      <div className="space-y-8">
        {/* Live status */}
        <section className="space-y-2.5">
          <div className="flex items-center gap-2 px-1">
            <Activity size={14} className="text-indigo-400" />
            <h2 className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">Operational Status</h2>
          </div>
          <Card className="border-border/40 bg-slate-900/30 shadow-premium">
            <RepoStatusPanel repo={repo} />
          </Card>
        </section>

        {/* History */}
        <section className="space-y-2.5">
          <div className="flex items-center justify-between px-1">
            <div className="flex items-center gap-2">
              <History size={14} className="text-indigo-400" />
              <h2 className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">System Events</h2>
            </div>
            {hasJobs && (
              <span className="text-[10px] font-medium text-slate-500 uppercase tracking-wider">{jobsData.total} logs</span>
            )}
          </div>

          {!hasJobs ? (
            <Card className="flex flex-col items-center justify-center py-12 text-center border-dashed border-white/10 bg-transparent">
              <History size={24} className="text-slate-700 mb-3" />
              <h3 className="text-sm font-semibold text-white mb-1">No event history</h3>
              <p className="text-xs text-slate-500 max-w-sm">
                Operational logs will appear here once background tasks are triggered.
              </p>
            </Card>
          ) : (
            <Card className="p-0 overflow-hidden border-border/40 bg-slate-950/40 shadow-premium">
              <RefreshJobsList repoId={repoId} initialJobs={jobsData.items} />
            </Card>
          )}
        </section>
      </div>
    </div>
  );
}
