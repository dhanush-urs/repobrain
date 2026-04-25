import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { SearchForm } from "@/components/repo/SearchForm";
import { Search } from "lucide-react";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoSearchPage({ params }: Props) {
  const { repoId } = await params;

  return (
    <div className="space-y-8 pb-16">
      <PageHeader
        title="Code Search"
        subtitle="Search symbols, routes, services, and code patterns across the indexed repository."
        icon={<Search className="h-5 w-5" />}
      />

      <RepoSubnav repoId={repoId} />

      <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
        <SearchForm repoId={repoId} />
      </div>
    </div>
  );
}
