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
    <div className="space-y-8 pb-20">
      <PageHeader
        title="File Explorer"
        subtitle="Search, filter, and inspect indexed repository files."
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
            <Card className="flex flex-col items-center justify-center py-24 text-center border-dashed border-white/10 bg-transparent">
              <div className="mb-6 rounded-full bg-slate-900/50 p-6 text-slate-500 ring-1 ring-white/10 shadow-inner">
                {isInProgress ? (
                  <Clock className="h-12 w-12 animate-pulse text-indigo-400" />
                ) : isError ? (
                  <AlertCircle className="h-12 w-12 text-rose-500" />
                ) : (
                  <Database className="h-12 w-12" />
                )}
              </div>
              
              <h3 className="text-2xl font-bold text-white mb-3 tracking-tight">
                {isInProgress ? "Indexing in Progress..." : isError ? "Indexing Failed" : "No files available"}
              </h3>
              
              <p className="text-slate-400 max-w-sm mx-auto leading-relaxed">
                {isInProgress 
                  ? "Repository file inventory is currently being built. Please check back in a few minutes." 
                  : isError 
                    ? "The repository could not be indexed successfully. Files cannot be displayed." 
                    : "Make sure the repository has been parsed before viewing files."}
              </p>
              
              {isInProgress && (
                <div className="mt-8 flex items-center gap-2 px-4 py-2 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-xs font-semibold text-indigo-400 uppercase tracking-widest">
                  <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 animate-ping" />
                  Analyzing Codebase
                </div>
              )}
            </Card>
          );
        }

        return (
          <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
            {isInProgress && (
              <div className="flex items-center gap-4 rounded-xl border border-indigo-500/30 bg-indigo-500/5 px-4 py-3 text-sm text-indigo-200 backdrop-blur-sm">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600/20 text-indigo-400 ring-1 ring-indigo-500/30">
                  <Clock className="h-4 w-4 animate-pulse" />
                </div>
                <div>
                  <span className="font-bold text-indigo-400">Indexing in progress:</span>
                  <p className="mt-0.5 text-xs text-slate-400">
                    File inventory and code analysis are actively running. Some files or metadata may not be visible yet.
                  </p>
                </div>
              </div>
            )}
            
            <div className="grid gap-4">
              <Card className="p-0 overflow-hidden border-white/5 bg-slate-900/40">
                <FileFilters repoId={repoId} files={data?.items || []} />
              </Card>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
