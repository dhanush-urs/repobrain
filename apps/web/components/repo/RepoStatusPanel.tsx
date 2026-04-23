import { Repository } from "@/lib/types";
import { Activity, CheckCircle2, Clock, Terminal, ShieldAlert } from "lucide-react";

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
    <div className="flex flex-col sm:flex-row items-start gap-6 p-6">
      <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl ring-1 transition-colors ${
        isSyncing ? "bg-amber-500/10 text-amber-500 ring-amber-500/20" :
        isError ? "bg-rose-500/10 text-rose-500 ring-rose-500/20" :
        "bg-emerald-500/10 text-emerald-500 ring-emerald-500/20"
      }`}>
        {isSyncing ? <Activity size={22} /> : isError ? <ShieldAlert size={22} /> : <CheckCircle2 size={22} />}
      </div>

      <div className="flex-1 space-y-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-white capitalize">{repo.status || "Unknown"}</span>
          </div>
          <p className="text-sm text-slate-400 leading-relaxed">{statusText}</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <MetricRow icon={<Clock size={14} />} label="Added" value={repo.created_at ? new Date(repo.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—"} />
          <MetricRow icon={<Terminal size={14} />} label="Language" value={repo.primary_language || "Unknown"} subValue={repo.framework ? sanitizeFramework(repo.framework) : undefined} />
        </div>
      </div>
    </div>
  );
}

function MetricRow({ icon, label, value, subValue }: { icon: React.ReactNode; label: string; value: string; subValue?: string }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-white/[0.02] border border-white/5 px-4 py-3">
      <span className="text-slate-500 shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="text-[10px] uppercase text-slate-500 font-semibold tracking-widest mb-0.5">{label}</p>
        <p className="text-sm text-slate-200 font-medium truncate">
          {value}
          {subValue && <span className="text-slate-500 ml-1.5">· {subValue}</span>}
        </p>
      </div>
    </div>
  );
}
