import { Repository } from "@/lib/types";
import { Activity, CheckCircle2, Clock, Terminal, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

export function RepoStatusPanel({ repo }: { repo: Repository }) {
  const isSyncing = ["indexing", "parsing", "embedding", "pending", "queued", "running"].includes(repo.status || "");
  const isError = repo.status === "failed";

  const sanitizeFramework = (val?: string | null) => {
    if (!val) return "";
    return val.replace(/[{}[\]"']/g, "").split(",").map(s => s.trim()).filter(Boolean).join(", ");
  };

  const statusText = isSyncing
    ? "Indexing in progress. The pipeline is actively processing your repository."
    : isError
    ? "Indexing failed. Review the refresh logs for error details."
    : repo.status === "embedded"
    ? "Indexing complete. The codebase is fully mapped and ready for AI analysis."
    : "Ready. Monitoring repository for changes.";

  return (
    <div className="flex flex-col sm:flex-row items-start gap-4 p-4">
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border transition-colors ${
        isSyncing ? "bg-amber-500/5 text-amber-500/80 border-amber-500/20" :
        isError ? "bg-rose-500/5 text-rose-500/80 border-rose-500/20" :
        "bg-emerald-500/5 text-emerald-500/80 border-emerald-500/20"
      }`}>
        {isSyncing ? <Activity size={18} /> : isError ? <ShieldAlert size={18} /> : <CheckCircle2 size={18} />}
      </div>

      <div className="flex-1 space-y-4">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className={cn(
              "text-[10px] font-bold uppercase tracking-wider",
              isSyncing ? "text-amber-500" : isError ? "text-rose-500" : "text-emerald-500"
            )}>
              {repo.status || "Unknown"}
            </span>
          </div>
          <p className="text-sm text-slate-300 font-medium leading-relaxed">{statusText}</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <MetricRow icon={<Clock size={12} />} label="Indexed" value={repo.created_at ? new Date(repo.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—"} />
          <MetricRow icon={<Terminal size={12} />} label="Stack" value={repo.primary_language || "Unknown"} subValue={repo.framework ? sanitizeFramework(repo.framework) : undefined} />
        </div>
      </div>
    </div>
  );
}

function MetricRow({ icon, label, value, subValue }: { icon: React.ReactNode; label: string; value: string; subValue?: string }) {
  return (
    <div className="flex items-center gap-3 rounded border border-white/5 bg-white/[0.01] px-3 py-2">
      <span className="text-slate-600 shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="text-[9px] uppercase text-slate-600 font-bold tracking-wider mb-0.5">{label}</p>
        <p className="text-[13px] text-slate-400 font-medium truncate">
          {value}
          {subValue && <span className="text-slate-600 ml-1.5 font-normal">· {subValue}</span>}
        </p>
      </div>
    </div>
  );
}
