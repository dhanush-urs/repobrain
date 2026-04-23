import { Card } from "@/components/common/Card";
import type { Repository } from "@/lib/types";

type Props = {
  repo: Repository;
};

export function RepoSummaryGrid({ repo }: Props) {
  const sanitizeFramework = (val?: string | null) => {
    if (!val) return "Unknown";
    return val.replace(/[{}[\]"']/g, "").split(",").map(s => s.trim()).filter(Boolean).join(", ");
  };

  const languages = repo.languages_used ?? [];

  const items = [
    { label: "Branch", value: repo.default_branch || "—" },
    { label: "Language", value: repo.primary_language || "Unknown" },
    { label: "Framework", value: sanitizeFramework(repo.framework) },
    { label: "Status", value: repo.status || "Unknown" },
  ];

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => (
          <Card key={item.label} className="py-4 px-5">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">
              {item.label}
            </div>
            <div className="text-sm font-semibold text-white truncate">{item.value}</div>
          </Card>
        ))}
      </div>

      {languages.length > 0 && (
        <Card className="py-4 px-5">
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-3">Languages</div>
          <div className="flex flex-wrap gap-2">
            {languages.map((lang) => (
              <span key={lang} className="rounded-full bg-slate-900 border border-white/10 px-3 py-1 text-xs text-slate-300 font-medium">
                {lang}
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
