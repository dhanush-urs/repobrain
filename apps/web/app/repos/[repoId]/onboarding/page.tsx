import { Card } from "@/components/common/Card";
import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { MarkdownView } from "@/components/repo/MarkdownView";
import { generateOnboarding, getOnboarding } from "@/lib/api";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoOnboardingPage({ params }: Props) {
  const { repoId } = await params;

  let doc = null;

  try {
    doc = await getOnboarding(repoId);
  } catch {
    try {
      await generateOnboarding(repoId);
      doc = await getOnboarding(repoId);
    } catch {
      doc = null;
    }
  }

  return (
    <div className="space-y-8 pb-20">
      <PageHeader
        title="Onboarding Guide"
        subtitle="AI-generated onboarding document for new engineers."
      />

      <RepoSubnav repoId={repoId} />

      {!doc ? (
        <EmptyState
          title="No onboarding document available"
          description="Generate onboarding from the backend API or ensure the repo has been parsed and embedded."
        />
      ) : (
        <Card className="p-8">
          <div className="mb-6 flex flex-wrap gap-3 text-[10px] font-bold uppercase tracking-widest text-slate-500 border-b border-white/5 pb-6">
            <span className="rounded bg-slate-900 px-2 py-1 ring-1 ring-white/5">v{doc.version || "1.0.0"}</span>
            <span className="rounded bg-slate-900 px-2 py-1 ring-1 ring-white/5">{doc.generation_mode || "standard"}</span>
            {doc.llm_model ? <span className="rounded bg-slate-900 px-2 py-1 ring-1 ring-white/5">{doc.llm_model}</span> : null}
          </div>

          <MarkdownView content={doc.content_markdown || "No content generated."} />
        </Card>
      )}
    </div>
  );
}
