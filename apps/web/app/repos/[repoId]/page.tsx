import Link from "next/link";
import { Card } from "@/components/common/Card";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { RepoActions } from "@/components/repo/RepoActions";
import { RepoSummaryGrid } from "@/components/repo/RepoSummaryGrid";
import { getRepository } from "@/lib/api";
import { Button } from "@/components/common/Button";
import { ArrowRight, ExternalLink, Github } from "lucide-react";
import { notFound } from "next/navigation";
import { cn } from "@/lib/utils";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoOverviewPage({ params }: Props) {
  const { repoId } = await params;

  let repo = null;
  try {
    repo = await getRepository(repoId);
  } catch (err) {
    console.error(`[Page] Error loading repo ${repoId}:`, err);
  }

  if (!repo) return notFound();

  const repoName = repo.repo_url?.split("/").pop() || "Unknown Repository";

  return (
    <div className="space-y-8 pb-16">
      {/* Repo header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-4 min-w-0">
          <div className="h-10 w-10 rounded-xl bg-indigo-500/10 flex items-center justify-center text-indigo-400 ring-1 ring-indigo-500/20 shrink-0">
            <Github className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-white tracking-tight truncate">{repoName}</h1>
            <p className="text-sm text-slate-500 font-mono truncate mt-0.5">{repo.repo_url}</p>
          </div>
        </div>
        <a href={repo.repo_url || "#"} target="_blank" rel="noopener noreferrer" className="shrink-0">
          <Button variant="outline" size="sm">
            <ExternalLink className="mr-2 h-4 w-4" />
            View on GitHub
          </Button>
        </a>
      </div>

      <RepoSubnav repoId={repoId} />

      {/* Summary stats */}
      <RepoSummaryGrid repo={repo} />

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Left: workflow + features */}
        <div className="lg:col-span-2 space-y-6">
          <div className="grid gap-6 md:grid-cols-2">
            <Card className="h-full">
              <h2 className="text-sm font-semibold text-white mb-4">Suggested Workflow</h2>
              <ul className="space-y-3">
                <WorkflowItem step={1} text="Parse the repository to extract symbols." />
                <WorkflowItem step={2} text="Embed the codebase for semantic search." />
                <WorkflowItem step={3} text="Identify risk hotspots in your code." />
                <WorkflowItem step={4} text="Run impact analysis on your PRs." />
              </ul>
            </Card>

            <Card className="h-full">
              <h2 className="text-sm font-semibold text-white mb-4">Features</h2>
              <div className="grid grid-cols-2 gap-2">
                {["Semantic Search", "Grounded Q&A", "Risk Hotspots", "Impact Engine", "AST Parsing", "Dependency Graph"].map((label) => (
                  <div key={label} className="rounded-lg bg-white/[0.03] border border-white/5 px-3 py-2 text-xs text-slate-400 text-center">
                    {label}
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>

        {/* Right: status + logs */}
        <div className="space-y-6">
          <Card className="border-indigo-500/20">
            <h2 className="text-sm font-semibold text-white mb-4">Indexing Status</h2>
            <RepoActions repoId={repoId} initialStatus={repo.status || "unknown"} />
            <div className="mt-6 pt-5 border-t border-white/10">
              <Link href={`/repos/${repoId}/refresh-jobs`}>
                <Button variant="indigo" className="w-full group">
                  View Refresh Logs
                  <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Button>
              </Link>
            </div>
          </Card>

          <Card>
            <h2 className="text-sm font-semibold text-white mb-3">Indexing Capabilities</h2>
            <div className="space-y-2.5">
              <InsightsItem text="Incremental re-parsing enabled" />
              <InsightsItem text="PR impact scoring ready" />
              <InsightsItem text="Symbol relationship mapping" />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function WorkflowItem({ step, text }: { step: number; text: string }) {
  return (
    <li className="flex items-start gap-3">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-800 text-[10px] font-bold text-indigo-400 ring-1 ring-white/10">
        {step}
      </span>
      <span className="text-sm text-slate-400 leading-snug">{text}</span>
    </li>
  );
}

function InsightsItem({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-400">
      <div className={cn("h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.4)]")} />
      {text}
    </div>
  );
}
