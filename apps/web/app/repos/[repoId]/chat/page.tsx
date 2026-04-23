import { PageHeader } from "@/components/common/PageHeader";
import { AskRepoForm } from "@/components/forms/AskRepoForm";
import { RepoSubnav } from "@/components/layout/RepoSubnav";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoChatPage({ params }: Props) {
  const { repoId } = await params;

  return (
    <div className="space-y-8 pb-20">
      <PageHeader
        title="Ask Repo"
        subtitle="Ask grounded questions about the indexed repository."
      />

      <RepoSubnav repoId={repoId} />

      <AskRepoForm repoId={repoId} />
    </div>
  );
}
