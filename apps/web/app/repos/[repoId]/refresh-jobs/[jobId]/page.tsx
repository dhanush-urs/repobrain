import Link from "next/link";
import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { RefreshJobDetail } from "@/components/refresh/RefreshJobDetail";
import { getRefreshJob } from "@/lib/api";
import { Card } from "@/components/common/Card";
import { Button } from "@/components/common/Button";
import { ArrowLeft, AlertCircle } from "lucide-react";

type Props = {
  params: Promise<{ repoId: string; jobId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RefreshJobDetailPage({ params }: Props) {
  const { repoId, jobId } = await params;

  let job = null;

  try {
    job = await getRefreshJob(jobId);
  } catch {
    job = null;
  }

  return (
    <div className="space-y-8 pb-20">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <PageHeader
          title="Job Detail"
          subtitle={`Job ID: ${jobId}`}
          className="mb-0"
        />
        <Link href={`/repos/${repoId}/refresh-jobs`}>
          <Button variant="outline" size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Jobs
          </Button>
        </Link>
      </div>

      <RepoSubnav repoId={repoId} />

      {!job ? (
        <Card className="flex flex-col items-center justify-center py-16 text-center border-dashed border-white/10 bg-transparent">
          <AlertCircle className="h-8 w-8 text-rose-500 mb-3" />
          <h3 className="text-base font-semibold text-white mb-1">Job Not Found</h3>
          <p className="text-sm text-slate-400 max-w-xs">
            This job record may have been purged or the ID is incorrect.
          </p>
        </Card>
      ) : (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
          <Card className="p-0 overflow-hidden border-white/5 bg-slate-950/40">
            <RefreshJobDetail initialJob={job} />
          </Card>
        </div>
      )}
    </div>
  );
}
