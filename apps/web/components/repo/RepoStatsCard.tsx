import { RepoStatusBadge } from "@/components/repo/RepoStatusBadge";
import type { Repository } from "@/lib/types";

type Props = {
  repo: Repository;
};

export function RepoStatsCard({ repo }: Props) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">Repository URL</div>
        <div className="break-all text-slate-300 font-mono text-xs leading-relaxed bg-slate-950/60 rounded-lg px-3 py-2 border border-white/5">
          {repo.repo_url}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 pt-1">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Branch</div>
          <div className="text-white font-medium">{repo.default_branch}</div>
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">Status</div>
          <RepoStatusBadge status={repo.status} />
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Language</div>
          <div className="text-white font-medium">{repo.primary_language || <span className="text-slate-500 italic text-xs">Unknown</span>}</div>
        </div>
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Framework</div>
          <div className="text-white font-medium">{repo.framework || <span className="text-slate-500 italic text-xs">Unknown</span>}</div>
        </div>
      </div>
    </div>
  );
}
