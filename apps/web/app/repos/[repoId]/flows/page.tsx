import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { Workflow } from "lucide-react";
import { FlowCanvas } from "@/components/repo/FlowCanvas";

type Props = {
  params: Promise<{ repoId: string }>;
  searchParams: Promise<{ mode?: string; query?: string; changed?: string }>;
};

export const dynamic = "force-dynamic";

export default async function FlowsPage({ params, searchParams }: Props) {
  const { repoId } = await params;
  const sp = await searchParams;

  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        title="Execution Map"
        subtitle="Infer and visualize likely execution paths through the repository."
        icon={<Workflow className="h-5 w-5" />}
        className="mb-0"
      />

      <RepoSubnav repoId={repoId} />

      <FlowCanvas
        repoId={repoId}
        initialMode={(sp.mode as any) || "primary"}
        initialQuery={sp.query || ""}
        initialChanged={sp.changed || ""}
      />
    </div>
  );
}
