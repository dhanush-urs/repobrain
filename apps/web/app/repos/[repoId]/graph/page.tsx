import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { getKnowledgeGraph } from "@/lib/api";
import { GitBranch } from "lucide-react";
import { KnowledgeGraphCanvas } from "@/components/repo/KnowledgeGraphCanvas";

type Props = {
  params: Promise<{ repoId: string }>;
  searchParams: Promise<{ view?: string; changed?: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoGraphPage({ params, searchParams }: Props) {
  const { repoId } = await params;
  const sp = await searchParams;
  const view = (sp.view as "clusters" | "files" | "hotspots" | "impact") || "clusters";
  const changed = sp.changed || "";

  const graphData = await getKnowledgeGraph(repoId, {
    view,
    changed: changed || undefined,
    max_nodes: 80,
  }).catch(() => ({
    view,
    repo_id: repoId,
    nodes: [],
    edges: [],
    legend: {},
    total_files: 0,
    total_resolved_edges: 0,
    truncated: false,
  } as import("@/lib/types").KnowledgeGraphData));

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        title="Knowledge Graph"
        subtitle="Visualize file relationships, module clusters, hotspots, and PR blast radius."
        icon={<GitBranch className="h-5 w-5" />}
        className="mb-0"
      />

      <RepoSubnav repoId={repoId} />

      <KnowledgeGraphCanvas
        repoId={repoId}
        initialData={graphData}
        initialView={view}
        initialChanged={changed}
      />
    </div>
  );
}
