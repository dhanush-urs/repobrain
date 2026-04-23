import { Badge } from "@/components/common/Badge";
import { Card } from "@/components/common/Card";
import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { getHotspots } from "@/lib/api";
import { AlertTriangle } from "lucide-react";

type Props = {
  params: Promise<{ repoId: string }>;
};

function riskTone(level: string): "rose" | "amber" | "green" | "slate" {
  if (level === "critical" || level === "high") return "rose";
  if (level === "medium") return "amber";
  if (level === "low") return "green";
  return "slate";
}

export const dynamic = "force-dynamic";

export default async function RepoHotspotsPage({ params }: Props) {
  const { repoId } = await params;

  let data = null;
  try {
    data = await getHotspots(repoId);
  } catch {
    data = null;
  }

  return (
    <div className="space-y-8 pb-16">
      <PageHeader
        title="Risk Hotspots"
        subtitle="Critical files with high complexity or dependency count."
        icon={<AlertTriangle className="h-5 w-5" />}
      />

      <RepoSubnav repoId={repoId} />

      {!data || !Array.isArray(data.items) || data.items.length === 0 ? (
        <EmptyState
          title="No hotspots available"
          description="Make sure the repository has been parsed before viewing hotspots."
        />
      ) : (
        <div className="grid gap-3">
          {data.items.map((item) => (
            <Card key={item.file_id} className="py-4 px-5">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-white truncate">{item.path || "Unknown path"}</div>
                  <div className="mt-1 text-xs text-slate-500">{item.language || "unknown"} · {item.file_kind || "file"}</div>
                </div>
                <Badge label={`${item.risk_level || "low"} · ${item.risk_score || 0}`} tone={riskTone(item.risk_level || "low")} />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4 border-t border-white/5 pt-4">
                <StatCell label="Complexity" value={item.complexity_score || 0} />
                <StatCell label="Dependency" value={item.dependency_score || 0} />
                <StatCell label="Inbound" value={item.inbound_dependencies || 0} />
                <StatCell label="Outbound" value={item.outbound_dependencies || 0} />
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function StatCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-0.5">
      <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
      <div className="text-sm font-semibold text-slate-200">{value}</div>
    </div>
  );
}
