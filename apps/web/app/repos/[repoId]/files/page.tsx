import { Card } from "@/components/common/Card";
import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { FileFilters } from "@/components/repo/FileFilters";
import { getRepositoryFiles } from "@/lib/api";
import { AlertCircle, Clock, Database } from "lucide-react";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoFilesPage({ params }: Props) {
  const { repoId } = await params;

  let data = null;

  try {
    data = await getRepositoryFiles(repoId, 300);
  } catch {
    data = null;
  }

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        title="File Explorer"
        subtitle="Browse and inspect indexed repository files."
        className="mb-0"
      />

      <RepoSubnav repoId={repoId} />

      {(() => {
        const hasData = data && Array.isArray(data.items);
        const isEmpty = !hasData || (data?.items?.length === 0);
        const status = (data?.status || "unknown").toLowerCase();
        
        const isError = status === "failed";
        const inProgressStates = ["pending", "queued", "running", "syncing", "indexing", "parsing", "embedding"];
        const isInProgress = inProgressStates.includes(status);

        if (isEmpty) {
          return (
            <Card className="flex flex-col items-center justify-center py-16 text-center border border-dashed border-white/5 bg-white/[0.01]">
              <div className="mb-4 rounded bg-slate-900/50 p-4 text-slate-700 border border-white/5 shadow-inner">
                {isInProgress ? (
                  <Clock size={20} className="animate-pulse text-indigo-500/60" />
                ) : isError ? (
                  <AlertCircle size={20} className="text-rose-500/60" />
                ) : (
                  <Database size={20} />
                )}
              </div>
              
              <h3 className="text-base font-bold text-slate-200 mb-1 tracking-tight">
                {isInProgress ? "Inventory Sync Active" : isError ? "Sync Failure" : "No Assets Detected"}
              </h3>
              
              <p className="text-[12px] text-slate-600 max-w-sm mx-auto leading-relaxed font-medium">
                {isInProgress 
                   ? "Building repository file inventory. High-fidelity intelligence will appear shortly." 
                  : isError 
                    ? "Repository indexing failed. Check operational logs for exception details." 
                    : "Initialize indexing to generate the codebase inventory."}
              </p>
              
              {isInProgress && (
                <div className="mt-6 flex items-center gap-2 px-2.5 py-1 rounded border border-indigo-500/20 bg-indigo-500/5 text-[9px] font-bold text-indigo-400 uppercase tracking-widest">
                  <div className="h-1 w-1 rounded-full bg-indigo-500/50 animate-pulse" />
                  Building Index
                </div>
              )}
            </Card>
          );
        }

        return (
          <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-500">
            {isInProgress && (
              <div className="flex items-center gap-3 rounded border border-indigo-500/20 bg-indigo-500/5 px-4 py-3 text-[11px] text-indigo-300/80 backdrop-blur-sm">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-slate-900 border border-indigo-500/20 text-indigo-400 shadow-inner">
                  <Clock size={14} className="animate-pulse" />
                </div>
                <div>
                  <span className="font-bold text-indigo-400 uppercase tracking-wider">Analysis Active</span>
                  <span className="ml-2 text-slate-500 font-medium leading-relaxed">
                    Codebase metadata and structural inventory are currently being synthesized.
                  </span>
                </div>
              </div>
            )}
            
            <div className="grid gap-4">
              <Card className="p-0 overflow-hidden border-border/40 bg-slate-900/40 shadow-premium">
                <FileFilters repoId={repoId} files={data?.items || []} />
              </Card>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
