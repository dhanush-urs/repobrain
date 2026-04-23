import Link from "next/link";
import { getRepositories } from "@/lib/api";
import type { Repository } from "@/lib/types";
import { Card } from "@/components/common/Card";
import { Badge } from "@/components/common/Badge";
import { Button } from "@/components/common/Button";
import { Plus, ChevronRight, Github, GitBranch, Database, AlertCircle } from "lucide-react";

export const dynamic = "force-dynamic";

export default async function ReposPage() {
  let repos: Repository[] = [];
  let error: string | null = null;

  try {
    repos = await getRepositories();
  } catch (err) {
    console.error("Failed to load repositories:", err);
    error = "Failed to load repositories. Please try again later.";
  }

  return (
    <div className="space-y-8 pb-16">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Repositories</h1>
          <p className="text-sm text-slate-400 mt-1">Manage and explore your indexed codebases.</p>
        </div>
        <Link href="/">
          <Button variant="indigo" size="md">
            <Plus className="mr-2 h-4 w-4" />
            Add Repository
          </Button>
        </Link>
      </div>

      {error && (
        <div className="rounded-xl bg-rose-500/10 border border-rose-500/20 p-4 text-sm text-rose-400 flex items-center gap-3">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {(!repos || repos.length === 0) ? (
        <Card className="flex flex-col items-center justify-center py-20 text-center border-dashed border-white/10 bg-transparent">
          <div className="mb-4 rounded-full bg-slate-900 p-4 text-slate-600">
            <Database className="h-8 w-8" />
          </div>
          <h3 className="text-lg font-semibold text-white mb-2">No repositories yet</h3>
          <p className="text-sm text-slate-400 max-w-xs mb-6">
            Connect your first repository to start indexing and exploring your codebase with AI.
          </p>
          <Link href="/">
            <Button variant="indigo" size="md">
              <Plus className="mr-2 h-4 w-4" />
              Add Repository
            </Button>
          </Link>
        </Card>
      ) : (
        <div className="grid gap-3">
          {repos.map((repo) => (
            <Link key={repo.id} href={`/repos/${repo.id}`} className="group block">
              <Card className="group-hover:border-indigo-500/40 transition-all duration-200">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-4 min-w-0">
                    <div className="rounded-lg bg-slate-900 p-2 text-slate-500 ring-1 ring-white/10 group-hover:text-indigo-400 group-hover:ring-indigo-500/30 transition-all shrink-0">
                      <Github className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-base font-semibold text-white group-hover:text-indigo-300 transition-colors truncate">
                        {repo.repo_url ? repo.repo_url.split("/").pop() : "Unnamed Repository"}
                      </h3>
                      <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-500">
                        <div className="flex items-center gap-1.5">
                          <GitBranch className="h-3 w-3" />
                          <span>{repo.default_branch || "main"}</span>
                        </div>
                        <span className="text-slate-700">·</span>
                        <span className="truncate max-w-[240px] font-mono text-[11px] hidden sm:block">
                          {repo.repo_url}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <Badge label={repo.status || "unknown"} />
                    <ChevronRight className="h-4 w-4 text-slate-600 group-hover:text-slate-300 transition-colors" />
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
