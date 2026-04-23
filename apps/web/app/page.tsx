import Link from "next/link";
import { Card } from "@/components/common/Card";
import { CreateRepoForm } from "@/components/forms/CreateRepoForm";
import { Button } from "@/components/common/Button";
import { Search, MessageSquare, Zap, ShieldAlert, ArrowRight } from "lucide-react";

export default function HomePage() {
  return (
    <div className="space-y-10 pb-16">
      {/* Hero */}
      <div className="pt-4">
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">
          Repository Intelligence
        </h1>
        <p className="text-slate-400 max-w-xl leading-relaxed">
          RepoBrain ingests repositories, parses code structure, and builds semantic graphs for search, Q&A, risk analysis, and change impact.
        </p>
      </div>

      <div className="grid gap-8 lg:grid-cols-3">
        {/* Left: features + CTA */}
        <div className="lg:col-span-2 space-y-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <FeatureItem icon={<Search className="h-4 w-4" />} title="Semantic Search" description="Query repository knowledge using embeddings and chunk retrieval." />
            <FeatureItem icon={<MessageSquare className="h-4 w-4" />} title="Ask Repo" description="Grounded Q&A powered by Gemini and retrieval context." />
            <FeatureItem icon={<ShieldAlert className="h-4 w-4" />} title="Risk Hotspots" description="Find risky files based on dependency centrality." />
            <FeatureItem icon={<Zap className="h-4 w-4" />} title="PR Impact" description="Estimate blast radius and review attention before merging." />
          </div>

          <Card className="border-indigo-500/10 bg-indigo-500/[0.03]">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-base font-semibold text-white mb-1">Browse Repositories</h3>
                <p className="text-sm text-slate-400">Open indexed repositories and use the full RepoBrain workflow.</p>
              </div>
              <Link href="/repos" className="shrink-0">
                <Button variant="indigo" size="md" className="group">
                  View Repositories
                  <ArrowRight className="ml-2 h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Button>
              </Link>
            </div>
          </Card>
        </div>

        {/* Right: add repo form */}
        <div className="space-y-6">
          <Card className="border-indigo-500/20">
            <h2 className="text-base font-semibold text-white mb-1">Add Repository</h2>
            <p className="text-sm text-slate-400 mb-5">
              Connect a GitHub repository to start indexing.
            </p>
            <CreateRepoForm />
          </Card>

          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-5">
            <h4 className="text-xs font-semibold text-slate-400 mb-4 uppercase tracking-widest">Platform Status</h4>
            <div className="space-y-3">
              <StatusRow label="Indexing Service" />
              <StatusRow label="Embeddings API" />
              <StatusRow label="Search Engine" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function FeatureItem({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="rounded-xl border border-white/5 bg-white/[0.02] p-4 hover:bg-white/[0.04] transition-colors">
      <div className="flex items-center gap-3 mb-2">
        <div className="rounded-lg bg-indigo-500/10 p-1.5 text-indigo-400 ring-1 ring-indigo-500/20">{icon}</div>
        <div className="text-sm font-semibold text-white">{title}</div>
      </div>
      <div className="text-sm text-slate-400 leading-relaxed">{description}</div>
    </div>
  );
}

function StatusRow({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-slate-500">{label}</span>
      <div className="flex items-center gap-1.5">
        <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)]" />
        <span className="text-emerald-400 font-medium">Operational</span>
      </div>
    </div>
  );
}
