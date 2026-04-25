import Link from "next/link";
import { Card } from "@/components/common/Card";
import { RepoSubnav } from "@/components/layout/RepoSubnav";
import { RepoActions } from "@/components/repo/RepoActions";
import { RepoSummaryGrid } from "@/components/repo/RepoSummaryGrid";
import { getRepository, getKnowledgeGraph, getExecutionFlow } from "@/lib/api";
import { Button } from "@/components/common/Button";
import { ArrowRight, ExternalLink, Github, GitBranch, Workflow, Search, MessageSquare, Zap, AlertCircle } from "lucide-react";
import { notFound } from "next/navigation";
import { cn } from "@/lib/utils";

type Props = {
  params: Promise<{ repoId: string }>;
};

export const dynamic = "force-dynamic";

export default async function RepoOverviewPage({ params }: Props) {
  const { repoId } = await params;

  let repo = null;
  try {
    repo = await getRepository(repoId);
  } catch (err) {
    console.error(`[Page] Error loading repo ${repoId}:`, err);
  }

  if (!repo) return notFound();

  const repoName = repo.repo_url?.split("/").pop() || "Unknown Repository";

  // Fetch graph stats and primary flow for repo-aware cards
  // Both are optional — degrade gracefully if unavailable
  let graphData = null;
  let flowData = null;
  try {
    graphData = await getKnowledgeGraph(repoId, { view: "clusters", max_nodes: 20 });
  } catch { /* graceful */ }
  try {
    flowData = await getExecutionFlow(repoId, { mode: "primary", depth: 3 });
  } catch { /* graceful */ }

  // Derive architecture snapshot from real data
  const graphStats = graphData?.graph_stats;
  const edgeCounts = graphData?.edge_type_counts || {};
  const totalResolved = graphData?.total_resolved_edges ?? 0;
  const totalInferred = graphData?.total_inferred_edges ?? 0;
  const isSparse = graphStats?.sparse ?? (totalResolved < 5);
  const graphQuality = isSparse ? "sparse" : graphStats?.density && graphStats.density > 0.5 ? "strong" : "partial";

  // Primary flow path
  const primaryPath = flowData?.paths?.[0];
  const selectedEntrypoint = flowData?.selected_entrypoint;
  const flowNodes = primaryPath?.nodes?.slice(0, 5) ?? [];
  const flowConfidence = flowData?.summary?.estimated_confidence ?? 0;

  // Detected capabilities from edge types
  const routeEdges = (edgeCounts["route_to_service"] ?? 0);
  const serviceEdges = (edgeCounts["service_to_model"] ?? 0);
  const apiEdges = (edgeCounts["inferred_api"] ?? 0);
  const symbolEdges = (edgeCounts["uses_symbol"] ?? 0);
  const importEdges = (edgeCounts["import"] ?? 0) + (edgeCounts["from_import"] ?? 0);

  // Detect layers from graph nodes
  const clusterPaths = (graphData?.nodes ?? []).map(n => n.path?.toLowerCase() ?? "");
  const hasRoutes = routeEdges > 0 || clusterPaths.some(p => /route|controller|handler|endpoint|api/.test(p));
  const hasServices = serviceEdges > 0 || clusterPaths.some(p => /service|usecase|manager/.test(p));
  const hasModels = clusterPaths.some(p => /model|schema|entity|orm/.test(p));
  const hasFrontend = apiEdges > 0 || clusterPaths.some(p => /frontend|client|ui|web|pages|components/.test(p));
  const hasConfig = clusterPaths.some(p => /config|settings|env|constants/.test(p));

  const detectedLayers = [
    hasFrontend && "Frontend",
    hasRoutes && "Routes / API",
    hasServices && "Services",
    hasModels && "Models / Schemas",
    hasConfig && "Config",
  ].filter(Boolean) as string[];

  return (
    <div className="space-y-6 pb-12">
      {/* Repo header */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="h-9 w-9 rounded-lg bg-indigo-500/10 flex items-center justify-center text-indigo-400 ring-1 ring-indigo-500/20 shrink-0">
            <Github size={18} />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-white tracking-tight truncate">{repoName}</h1>
            <p className="text-[11px] text-slate-500 font-mono truncate mt-0.5">{repo.repo_url}</p>
          </div>
        </div>
        <a href={repo.repo_url || "#"} target="_blank" rel="noopener noreferrer" className="shrink-0">
          <Button variant="outline" size="sm">
            <ExternalLink className="mr-2 h-3.5 w-3.5" />
            View on GitHub
          </Button>
        </a>
      </div>

      <RepoSubnav repoId={repoId} />

      {/* Summary stats */}
      <RepoSummaryGrid repo={repo} />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: repo-aware architecture + capabilities */}
        <div className="lg:col-span-2 space-y-6">
          <div className="grid gap-6 md:grid-cols-2">

            {/* Architecture Snapshot — repo-aware */}
            <Card className="h-full">
              <h2 className="text-xs font-semibold text-slate-200 mb-4">Architecture Snapshot</h2>
              {selectedEntrypoint || flowNodes.length > 0 ? (
                <div className="space-y-4">
                  {selectedEntrypoint && (
                    <div>
                      <div className="text-[10px] font-medium text-slate-500 mb-1.5 uppercase tracking-wider">Entry</div>
                      <code className="text-xs text-indigo-300 font-mono bg-indigo-500/5 px-1.5 py-0.5 rounded border border-indigo-500/10">{selectedEntrypoint.split("/").pop()}</code>
                      <span className="text-[10px] text-slate-600 ml-2 font-mono">{selectedEntrypoint.includes("/") ? selectedEntrypoint.split("/").slice(0, -1).join("/") : ""}</span>
                    </div>
                  )}
                  {flowNodes.length > 1 && (
                    <div>
                      <div className="text-[10px] font-medium text-slate-500 mb-1.5 uppercase tracking-wider">Primary Flow</div>
                      <div className="flex flex-wrap items-center gap-1.5 text-[11px] font-mono">
                        {flowNodes.map((n, i) => (
                          <span key={n.id} className="flex items-center gap-1.5">
                            <span className="text-slate-400">{n.label}</span>
                            {i < flowNodes.length - 1 && <span className="text-slate-700">→</span>}
                          </span>
                        ))}
                      </div>
                      {flowConfidence > 0 && (
                        <div className="mt-1.5 text-[10px] text-slate-600 font-medium">
                          {flowConfidence >= 0.7 ? "High-confidence semantic edges" : flowConfidence >= 0.4 ? "Partial inference" : "Heuristic fallback"}
                        </div>
                      )}
                    </div>
                  )}
                  {detectedLayers.length > 0 && (
                    <div>
                      <div className="text-[10px] font-medium text-slate-500 mb-2 uppercase tracking-wider">Layers</div>
                      <div className="flex flex-wrap gap-1.5">
                        {detectedLayers.map(layer => (
                          <span key={layer} className="rounded bg-slate-900 border border-white/5 px-2 py-0.5 text-[10px] text-slate-400">{layer}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {isSparse && (
                    <p className="text-[10px] text-slate-600 italic">Graph sparse — re-index for richer analysis.</p>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-slate-500">Parse and index the repository to generate an architecture snapshot.</p>
                  {detectedLayers.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      {detectedLayers.map(layer => (
                        <span key={layer} className="rounded bg-slate-900 border border-white/5 px-2 py-0.5 text-[10px] text-slate-400">{layer}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </Card>

            {/* Detected Capabilities — repo-aware */}
            <Card className="h-full">
              <h2 className="text-xs font-semibold text-slate-200 mb-4">Detected Signals</h2>
              {(totalResolved > 0 || totalInferred > 0) ? (
                <div className="space-y-2.5">
                  {[
                    routeEdges > 0 && { label: `${routeEdges} route → service link${routeEdges !== 1 ? "s" : ""}`, color: "text-indigo-400/80" },
                    serviceEdges > 0 && { label: `${serviceEdges} service → model link${serviceEdges !== 1 ? "s" : ""}`, color: "text-violet-400/80" },
                    apiEdges > 0 && { label: `${apiEdges} frontend → API link${apiEdges !== 1 ? "s" : ""}`, color: "text-amber-400/80" },
                    symbolEdges > 0 && { label: `${symbolEdges} symbol usage link${symbolEdges !== 1 ? "s" : ""}`, color: "text-cyan-400/80" },
                    importEdges > 0 && { label: `${importEdges} import edge${importEdges !== 1 ? "s" : ""}`, color: "text-slate-400/80" },
                    totalResolved > 0 && { label: `${totalResolved} resolved edge${totalResolved !== 1 ? "s" : ""}`, color: "text-emerald-400/80" },
                    totalInferred > 0 && { label: `${totalInferred} inferred edge${totalInferred !== 1 ? "s" : ""}`, color: "text-slate-500" },
                  ].filter(Boolean).map((item: any, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <div className="h-1 w-1 rounded-full bg-current shrink-0 opacity-60" style={{ color: "inherit" }} />
                      <span className={cn("font-medium", item.color)}>{item.label}</span>
                    </div>
                  ))}
                  <div className="pt-2 mt-2 border-t border-white/5">
                    <span className={cn("text-[10px] font-semibold uppercase tracking-wider",
                      graphQuality === "strong" ? "text-emerald-400" : graphQuality === "partial" ? "text-amber-400" : "text-slate-500"
                    )}>
                      Analysis: {graphQuality === "strong" ? "Strong" : graphQuality === "partial" ? "Partial" : "Sparse"}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-500 leading-relaxed">No graph data yet. Parse and index the repository to detect relationships.</p>
              )}
            </Card>
          </div>

          {/* Smart Actions */}
          <Card>
            <h2 className="text-xs font-semibold text-slate-200 mb-3">Quick Actions</h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Link href={`/repos/${repoId}/chat`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-[11px] h-7 px-2 hover:bg-white/5">
                  <MessageSquare size={14} className="mr-2 text-indigo-400" />
                  Ask what this does
                </Button>
              </Link>
              <Link href={`/repos/${repoId}/flows`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-[11px] h-7 px-2 hover:bg-white/5">
                  <Workflow size={14} className="mr-2 text-violet-400" />
                  View primary flow
                </Button>
              </Link>
              <Link href={`/repos/${repoId}/graph`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-[11px] h-7 px-2 hover:bg-white/5">
                  <GitBranch size={14} className="mr-2 text-cyan-400" />
                  Knowledge graph
                </Button>
              </Link>
              <Link href={`/repos/${repoId}/search`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-[11px] h-7 px-2 hover:bg-white/5">
                  <Search size={14} className="mr-2 text-amber-400" />
                  Search codebase
                </Button>
              </Link>
              <Link href={`/repos/${repoId}/impact`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-[11px] h-7 px-2 hover:bg-white/5">
                  <Zap size={14} className="mr-2 text-rose-400" />
                  Analyze PR impact
                </Button>
              </Link>
              {selectedEntrypoint && (
                <Link href={`/repos/${repoId}/flows?mode=primary`}>
                  <Button variant="ghost" size="sm" className="w-full justify-start text-[11px] h-7 px-2 hover:bg-white/5">
                    <ArrowRight size={14} className="mr-2 text-emerald-400" />
                    Trace from entry
                  </Button>
                </Link>
              )}
            </div>
          </Card>
        </div>

        {/* Right: status + graph health */}
        <div className="space-y-6">
          <Card className="border-indigo-500/20 shadow-premium shadow-indigo-500/5">
            <h2 className="text-xs font-semibold text-slate-200 mb-4">Indexing Status</h2>
            <RepoActions repoId={repoId} initialStatus={repo.status || "unknown"} />
            <div className="mt-6 pt-5 border-t border-white/5">
              <Link href={`/repos/${repoId}/refresh-jobs`}>
                <Button variant="outline" size="sm" className="w-full group">
                  View Refresh Logs
                  <ArrowRight size={14} className="ml-2 transition-transform group-hover:translate-x-0.5" />
                </Button>
              </Link>
            </div>
          </Card>

          {/* Graph health — repo-aware */}
          <Card>
            <h2 className="text-xs font-semibold text-slate-200 mb-4">Graph Health</h2>
            <div className="space-y-3">
              <HealthItem
                label="Graph quality"
                value={graphQuality === "strong" ? "Strong" : graphQuality === "partial" ? "Partial" : "Sparse"}
                tone={graphQuality === "strong" ? "green" : graphQuality === "partial" ? "amber" : "slate"}
              />
              {totalResolved > 0 && (
                <HealthItem label="Typed edges" value={String(totalResolved + totalInferred)} tone="neutral" />
              )}
              {flowConfidence > 0 && (
                <HealthItem
                  label="Flow confidence"
                  value={flowConfidence >= 0.7 ? "High" : flowConfidence >= 0.4 ? "Medium" : "Low"}
                  tone={flowConfidence >= 0.7 ? "green" : flowConfidence >= 0.4 ? "amber" : "slate"}
                />
              )}
              {isSparse && totalResolved === 0 && (
                <div className="flex items-start gap-2 text-[10px] text-amber-400/70 mt-2 bg-amber-500/5 p-2 rounded border border-amber-500/10">
                  <AlertCircle size={12} className="shrink-0 mt-0.5" />
                  Re-index to populate dependency graph
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function HealthItem({ label, value, tone }: { label: string; value: string; tone: "green" | "amber" | "slate" | "neutral" }) {
  const dotColor = tone === "green" ? "bg-emerald-500" : tone === "amber" ? "bg-amber-500" : "bg-slate-600";
  const textColor = tone === "green" ? "text-emerald-400" : tone === "amber" ? "text-amber-400" : tone === "neutral" ? "text-slate-300" : "text-slate-500";
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-slate-500">{label}</span>
      <div className="flex items-center gap-1.5">
        <div className={cn("h-1.5 w-1.5 rounded-full", dotColor)} />
        <span className={cn("font-medium", textColor)}>{value}</span>
      </div>
    </div>
  );
}
