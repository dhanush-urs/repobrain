import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { Zap } from "lucide-react";
import { ImpactForm } from "@/components/forms/ImpactForm";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoImpactPage({ params }: Props) {
  const { repoId } = await params;

  return (
    <div className="space-y-8 pb-16">
      <PageHeader
        title="PR Impact Analysis"
        subtitle="Paste a diff or list changed files to analyze blast radius and review priority."
        icon={<Zap className="h-5 w-5" />}
      />

      <RepoSubnav repoId={repoId} />

      <ImpactForm repoId={repoId} />
    </div>
  );
}
