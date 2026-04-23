"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { KnowledgeGraphNode, KnowledgeGraphEdge, KnowledgeGraphData } from "@/lib/types";
import { getKnowledgeGraph } from "@/lib/api";
import {
  Search, X, ZoomIn, ZoomOut, Maximize2, RefreshCw,
  GitBranch, AlertCircle, Info, ChevronRight,
  ArrowUpRight, ArrowDownLeft, Layers, FileCode,
  Flame, Zap, Workflow
} from "lucide-react";
import { Button } from "@/components/common/Button";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ViewMode = "clusters" | "files" | "hotspots" | "impact";

interface SimNode extends KnowledgeGraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface SimEdge extends KnowledgeGraphEdge {
  sourceNode?: SimNode;
  targetNode?: SimNode;
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------

function nodeColor(node: SimNode, view: ViewMode): string {
  if (view === "hotspots") {
    if (node.risk_score >= 70) return "#ef4444";   // red
    if (node.risk_score >= 40) return "#f97316";   // orange
    return "#22c55e";                               // green
  }
  if (view === "impact") {
    if (node.meta.changed) return "#ef4444";        // red = changed
    if (node.meta.impacted) return "#f97316";       // orange = impacted
    return "#6366f1";                               // indigo = unaffected
  }
  // clusters / files
  if (node.type === "cluster") {
    const kind = node.file_kind?.toLowerCase() || "source";
    const clusterColors: Record<string, string> = {
      source: "#6366f1", test: "#f59e0b", config: "#10b981",
      doc: "#64748b", generated: "#374151", vendor: "#374151",
    };
    return clusterColors[kind] || "#6366f1";
  }
  if (node.is_vendor || node.is_generated) return "#374151";
  if (node.is_test) return "#f59e0b";
  const kind = node.file_kind?.toLowerCase() || "source";
  const fileColors: Record<string, string> = {
    source: "#6366f1", test: "#f59e0b", config: "#10b981",
    doc: "#64748b", generated: "#374151",
  };
  return fileColors[kind] || "#6366f1";
}

function nodeRadius(node: SimNode): number {
  if (node.type === "cluster") {
    return Math.max(14, Math.min(32, 12 + Math.sqrt(node.meta.file_count) * 3));
  }
  const base = 7;
  return base + Math.min(node.degree * 0.5, 10);
}

// ---------------------------------------------------------------------------
// Force layout
// ---------------------------------------------------------------------------

function initLayout(nodes: KnowledgeGraphNode[], W: number, H: number): SimNode[] {
  const cx = W / 2, cy = H / 2;
  const r = Math.min(W, H) * 0.32;
  return nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    return {
      ...n,
      x: cx + r * Math.cos(angle) + (Math.random() - 0.5) * 50,
      y: cy + r * Math.sin(angle) + (Math.random() - 0.5) * 50,
      vx: 0, vy: 0,
    };
  });
}

function runLayout(nodes: SimNode[], edges: SimEdge[], W: number, H: number, iters = 220): SimNode[] {
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const cx = W / 2, cy = H / 2;
  let alpha = 0.3;

  for (let it = 0; it < iters; it++) {
    alpha = Math.max(0.001, alpha * 0.978);

    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const d2 = dx * dx + dy * dy + 1;
        const d = Math.sqrt(d2);
        const rep = 3200 / d2 * alpha;
        const fx = dx / d * rep, fy = dy / d * rep;
        a.vx += fx; a.vy += fy;
        b.vx -= fx; b.vy -= fy;
      }
    }

    // Attraction
    for (const e of edges) {
      const s = nodeMap.get(e.source), t = nodeMap.get(e.target);
      if (!s || !t) continue;
      const dx = t.x - s.x, dy = t.y - s.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const ideal = 130 + Math.min(e.weight, 8) * 8;
      const f = (d - ideal) * 0.035 * alpha;
      const fx = dx / d * f, fy = dy / d * f;
      s.vx += fx; s.vy += fy;
      t.vx -= fx; t.vy -= fy;
    }

    // Center gravity
    for (const n of nodes) {
      n.vx += (cx - n.x) * 0.007 * alpha;
      n.vy += (cy - n.y) * 0.007 * alpha;
    }

    // Integrate
    for (const n of nodes) {
      n.vx *= 0.84; n.vy *= 0.84;
      n.x = Math.max(40, Math.min(W - 40, n.x + n.vx));
      n.y = Math.max(40, Math.min(H - 40, n.y + n.vy));
    }
  }
  return nodes;
}

// ---------------------------------------------------------------------------
// View config
// ---------------------------------------------------------------------------

const VIEW_CONFIG: Record<ViewMode, { label: string; icon: React.ReactNode; desc: string }> = {
  clusters:  { label: "Cluster View",    icon: <Layers className="h-3.5 w-3.5" />,   desc: "Architecture-level module and folder relationships" },
  files:     { label: "File View",       icon: <FileCode className="h-3.5 w-3.5" />, desc: "File-to-file dependency graph" },
  hotspots:  { label: "Hotspot Overlay", icon: <Flame className="h-3.5 w-3.5" />,    desc: "Risk-weighted dependency view" },
  impact:    { label: "Impact Overlay",  icon: <Zap className="h-3.5 w-3.5" />,      desc: "Changed files and directly affected dependents" },
};


// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type Props = {
  repoId: string;
  initialData: KnowledgeGraphData;
  initialView: ViewMode;
  initialChanged: string;
};

export function KnowledgeGraphCanvas({ repoId, initialData, initialView, initialChanged }: Props) {
  const router = useRouter();
  const svgRef = useRef<SVGSVGElement>(null);

  const [graphData, setGraphData] = useState<KnowledgeGraphData>(initialData);
  const [view, setView] = useState<ViewMode>(initialView);
  const [changedInput, setChangedInput] = useState(initialChanged);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simEdges, setSimEdges] = useState<SimEdge[]>([]);
  const [layoutDone, setLayoutDone] = useState(false);

  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });

  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const W = 900, H = 600;

  // ── Layout ────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!graphData.nodes.length) {
      setSimNodes([]); setSimEdges([]); setLayoutDone(true); return;
    }
    setLayoutDone(false);
    const nodes = initLayout(graphData.nodes, W, H);
    const edges: SimEdge[] = graphData.edges.map(e => ({ ...e }));
    setTimeout(() => {
      const laid = runLayout(nodes, edges, W, H, 240);
      const nm = new Map(laid.map(n => [n.id, n]));
      setSimNodes(laid);
      setSimEdges(edges.map(e => ({ ...e, sourceNode: nm.get(e.source), targetNode: nm.get(e.target) })));
      setLayoutDone(true);
    }, 0);
  }, [graphData]);

  // ── Search ────────────────────────────────────────────────────────────────
  const searchMatches = useMemo(() => {
    if (!searchQuery.trim()) return new Set<string>();
    const q = searchQuery.toLowerCase();
    return new Set(simNodes.filter(n => (n.path || n.label).toLowerCase().includes(q)).map(n => n.id));
  }, [simNodes, searchQuery]);

  const neighborIds = useMemo(() => {
    if (!selectedNode) return new Set<string>();
    const ids = new Set<string>();
    for (const e of simEdges) {
      if (e.source === selectedNode.id) ids.add(e.target);
      if (e.target === selectedNode.id) ids.add(e.source);
    }
    return ids;
  }, [selectedNode, simEdges]);

  const isVisible = useCallback((n: SimNode) => {
    if (searchQuery.trim() && !searchMatches.has(n.id)) return false;
    return true;
  }, [searchQuery, searchMatches]);

  // ── Pan / zoom ────────────────────────────────────────────────────────────
  const onMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(".kg-node")) return;
    isPanning.current = true;
    panStart.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
    e.preventDefault();
  }, [transform]);

  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!isPanning.current) return;
    setTransform(t => ({ ...t, x: panStart.current.tx + e.clientX - panStart.current.x, y: panStart.current.ty + e.clientY - panStart.current.y }));
  }, []);

  const onMouseUp = useCallback(() => { isPanning.current = false; }, []);

  const onWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    setTransform(t => ({ ...t, scale: Math.max(0.12, Math.min(4, t.scale * (e.deltaY < 0 ? 1.12 : 0.89))) }));
  }, []);

  const fitView = useCallback(() => {
    if (!simNodes.length) return;
    const xs = simNodes.map(n => n.x), ys = simNodes.map(n => n.y);
    const minX = Math.min(...xs) - 50, maxX = Math.max(...xs) + 50;
    const minY = Math.min(...ys) - 50, maxY = Math.max(...ys) + 50;
    const scale = Math.min(W / (maxX - minX), H / (maxY - minY), 2);
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
    setTransform({ scale, x: W / 2 - cx * scale, y: H / 2 - cy * scale });
  }, [simNodes]);

  // ── Load ──────────────────────────────────────────────────────────────────
  const loadGraph = useCallback(async (v: ViewMode, ch?: string) => {
    setLoading(true); setError(null); setSelectedNode(null);
    try {
      const data = await getKnowledgeGraph(repoId, {
        view: v, changed: ch || undefined, max_nodes: 80,
      });
      setGraphData(data);
      setView(v);
    } catch {
      setError("Failed to load graph.");
    } finally {
      setLoading(false);
    }
  }, [repoId]);

  const switchView = useCallback((v: ViewMode) => {
    loadGraph(v, v === "impact" ? changedInput : undefined);
  }, [loadGraph, changedInput]);

  // ── Empty state ───────────────────────────────────────────────────────────
  const isEmpty = graphData.nodes.length === 0;

  return (
    <div className="flex flex-col gap-3">
      {/* View selector */}
      <div className="flex flex-wrap items-center gap-2">
        {(Object.entries(VIEW_CONFIG) as [ViewMode, typeof VIEW_CONFIG[ViewMode]][]).map(([v, cfg]) => (
          <button
            key={v}
            onClick={() => switchView(v)}
            className={cn(
              "flex items-center gap-2 h-8 px-3 rounded-lg text-xs font-medium transition-all border",
              view === v
                ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300"
                : "border-white/5 text-slate-400 hover:text-white hover:bg-white/5"
            )}
          >
            {cfg.icon}
            {cfg.label}
          </button>
        ))}

        {/* Impact changed-files input */}
        {view === "impact" && (
          <div className="flex items-center gap-2 ml-1">
            <input
              value={changedInput}
              onChange={e => setChangedInput(e.target.value)}
              placeholder="app/auth.py,app/models.py"
              className="h-8 px-3 rounded-lg bg-slate-900 border border-white/10 text-xs text-slate-200 placeholder:text-slate-600 outline-none focus:border-indigo-500/50 w-56"
            />
            <Button
              variant="indigo" size="sm"
              onClick={() => loadGraph("impact", changedInput)}
              disabled={loading}
              className="h-8 px-3 text-xs"
            >
              Analyze
            </Button>
          </div>
        )}

        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => setTransform(t => ({ ...t, scale: Math.min(4, t.scale * 1.2) }))}
            className="h-7 w-7 flex items-center justify-center rounded-lg border border-white/5 text-slate-400 hover:text-white hover:bg-white/5">
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => setTransform(t => ({ ...t, scale: Math.max(0.12, t.scale * 0.83) }))}
            className="h-7 w-7 flex items-center justify-center rounded-lg border border-white/5 text-slate-400 hover:text-white hover:bg-white/5">
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <button onClick={fitView}
            className="h-7 w-7 flex items-center justify-center rounded-lg border border-white/5 text-slate-400 hover:text-white hover:bg-white/5">
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
          <button onClick={() => loadGraph(view, view === "impact" ? changedInput : undefined)}
            className="h-7 w-7 flex items-center justify-center rounded-lg border border-white/5 text-slate-400 hover:text-white hover:bg-white/5">
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Mode description strip */}
      <div className="flex items-center gap-3">
        <p className="text-xs text-slate-500 leading-none">
          {VIEW_CONFIG[view].desc}
        </p>
      </div>

      {/* Stats + search strip */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Search */}
        <div className="relative min-w-[160px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={view === "clusters" ? "Search clusters…" : "Search files…"}
            className="w-full pl-9 pr-3 h-8 rounded-lg bg-slate-900 border border-white/10 text-sm text-slate-200 placeholder:text-slate-600 outline-none focus:border-indigo-500/50 transition-colors"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white">
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* Stats chips */}
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/5 bg-white/[0.02] px-2.5 py-1 text-[10px] text-slate-500">
          {graphData.nodes.length} {view === "clusters" ? "clusters" : "files"}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/5 bg-white/[0.02] px-2.5 py-1 text-[10px] text-slate-500">
          {graphData.edges.length} edges
        </span>
        {graphData.truncated && (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/20 bg-amber-500/5 px-2.5 py-1 text-[10px] text-amber-400/80">
            <Info className="h-3 w-3" /> top {graphData.nodes.length} shown
          </span>
        )}
        {view === "impact" && changedInput && (
          <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/20 bg-rose-500/5 px-2.5 py-1 text-[10px] text-rose-400/80 max-w-[200px] truncate">
            {changedInput.split(",").filter(Boolean).length} changed file(s)
          </span>
        )}
      </div>

      <div className="flex gap-4 items-start animate-in fade-in duration-500">
        {/* Canvas */}
        <div className="flex-1 min-w-0">
          <div className="relative rounded-xl border border-white/5 bg-slate-950/60 overflow-hidden" style={{ height: H }}>
            {(loading || !layoutDone) && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-950/70 z-10">
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  {loading ? "Loading…" : "Computing layout…"}
                </div>
              </div>
            )}

            {isEmpty && !loading && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
                <div className="h-14 w-14 rounded-xl bg-slate-900 flex items-center justify-center text-slate-500 ring-1 ring-white/10">
                  <GitBranch className="h-7 w-7" />
                </div>
                <div className="text-center">
                  <p className="text-sm font-semibold text-white mb-1">No graph data available</p>
                  <p className="text-xs text-slate-400 max-w-xs">
                    {graphData.total_resolved_edges === 0 && !graphData.total_inferred_edges
                      ? "No file relationships found. Re-index the repository to populate dependency edges."
                      : "No files found. Index the repository first."}
                  </p>
                </div>
                <Link href={`/repos/${repoId}/refresh-jobs`}>
                  <Button variant="outline" size="sm">View Refresh Jobs</Button>
                </Link>
              </div>
            )}

            {error && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="flex items-center gap-2 text-sm text-rose-400">
                  <AlertCircle className="h-4 w-4" /> {error}
                </div>
              </div>
            )}

            <svg
              ref={svgRef}
              width={W} height={H}
              className="w-full h-full cursor-grab active:cursor-grabbing select-none"
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={onMouseUp}
              onWheel={onWheel}
              onClick={() => setSelectedNode(null)}
            >
              <defs>
                <marker id="kg-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L6,3 z" fill="rgba(99,102,241,0.5)" />
                </marker>
                <marker id="kg-arrow-inferred" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                  <path d="M0,0 L0,6 L6,3 z" fill="rgba(99,102,241,0.25)" />
                </marker>
              </defs>

              <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
                {/* Edges */}
                {layoutDone && simEdges.map(edge => {
                  const s = edge.sourceNode, t = edge.targetNode;
                  if (!s || !t) return null;
                  if (!isVisible(s) || !isVisible(t)) return null;
                  const isHot = hoveredNode === s.id || hoveredNode === t.id
                    || selectedNode?.id === s.id || selectedNode?.id === t.id;
                  const isInferred = edge.meta?.is_inferred === true
                    || edge.edge_type === "inferred"
                    || edge.edge_type === "inferred_naming";
                  const dx = t.x - s.x, dy = t.y - s.y;
                  const len = Math.sqrt(dx * dx + dy * dy) || 1;
                  const nx = -dy / len * 3, ny = dx / len * 3;
                  return (
                    <line
                      key={edge.id}
                      x1={s.x + nx} y1={s.y + ny}
                      x2={t.x + nx} y2={t.y + ny}
                      stroke={isInferred ? "#818cf8" : "#6366f1"}
                      strokeWidth={isHot ? 1.8 : Math.min(1 + (edge.weight || 1) * 0.2, 3)}
                      strokeOpacity={isHot ? (isInferred ? 0.5 : 0.7) : (isInferred ? 0.1 : 0.15)}
                      strokeDasharray={isInferred ? "4 3" : undefined}
                      markerEnd={isInferred ? "url(#kg-arrow-inferred)" : "url(#kg-arrow)"}
                      style={{ transition: "stroke-opacity 0.12s" }}
                    />
                  );
                })}

                {/* Nodes */}
                {layoutDone && simNodes.map(node => {
                  if (!isVisible(node)) return null;
                  const r = nodeRadius(node);
                  const color = nodeColor(node, view);
                  const isSel = selectedNode?.id === node.id;
                  const isHov = hoveredNode === node.id;
                  const isNeighbor = neighborIds.has(node.id);
                  const dimmed = selectedNode && !isSel && !isNeighbor;
                  const isCluster = node.type === "cluster";

                  return (
                    <g
                      key={node.id}
                      className="kg-node"
                      transform={`translate(${node.x},${node.y})`}
                      style={{ cursor: "pointer" }}
                      onClick={e => { e.stopPropagation(); setSelectedNode(isSel ? null : node); }}
                      onMouseEnter={() => setHoveredNode(node.id)}
                      onMouseLeave={() => setHoveredNode(null)}
                    >
                      {(isSel || isHov) && (
                        <circle r={r + 6} fill="none" stroke={color}
                          strokeWidth={isSel ? 2 : 1} strokeOpacity={0.4} />
                      )}
                      {isCluster ? (
                        <rect
                          x={-r} y={-r} width={r * 2} height={r * 2}
                          rx={r * 0.4}
                          fill={color}
                          fillOpacity={dimmed ? 0.12 : isSel ? 1 : 0.65}
                          stroke={isSel ? color : "rgba(255,255,255,0.15)"}
                          strokeWidth={isSel ? 2 : 1}
                          style={{ transition: "fill-opacity 0.12s" }}
                        />
                      ) : (
                        <circle
                          r={r}
                          fill={color}
                          fillOpacity={dimmed ? 0.12 : isSel ? 1 : isNeighbor ? 0.85 : 0.7}
                          stroke={isSel ? color : "rgba(255,255,255,0.15)"}
                          strokeWidth={isSel ? 2 : 1}
                          style={{ transition: "fill-opacity 0.12s" }}
                        />
                      )}
                      {/* Changed/impacted ring */}
                      {node.meta.changed && (
                        <circle r={r + 3} fill="none" stroke="#ef4444" strokeWidth={2} strokeOpacity={0.8} strokeDasharray="4 2" />
                      )}
                      {node.meta.impacted && !node.meta.changed && (
                        <circle r={r + 3} fill="none" stroke="#f97316" strokeWidth={1.5} strokeOpacity={0.6} strokeDasharray="3 2" />
                      )}
                      {transform.scale > 0.45 && (
                        <text
                          y={r + 12}
                          textAnchor="middle"
                          fontSize={transform.scale > 1 ? 9 : 8}
                          fill={dimmed ? "rgba(255,255,255,0.18)" : "rgba(255,255,255,0.8)"}
                          style={{ pointerEvents: "none", userSelect: "none" }}
                        >
                          {node.label.length > 16 ? node.label.slice(0, 14) + "…" : node.label}
                        </text>
                      )}
                      {isCluster && transform.scale > 0.6 && (
                        <text
                          y={r + 22}
                          textAnchor="middle"
                          fontSize={7}
                          fill="rgba(255,255,255,0.35)"
                          style={{ pointerEvents: "none", userSelect: "none" }}
                        >
                          {node.meta.file_count} files
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>

            {/* Legend */}
            <div className="absolute bottom-3 left-3 flex flex-wrap gap-3">
              {Object.entries(graphData.legend || {}).map(([color, label]) => {
                const dotColors: Record<string, string> = {
                  red: "#ef4444", orange: "#f97316", green: "#22c55e",
                  blue: "#6366f1", indigo: "#6366f1", amber: "#f59e0b",
                  emerald: "#10b981", slate: "#64748b",
                };
                return (
                  <div key={color} className="flex items-center gap-1.5 text-[10px] text-slate-500">
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: dotColors[color] || "#6366f1" }} />
                    {label}
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Side panel */}
        <div className="w-64 shrink-0">
          {selectedNode ? (
            <NodePanel
              node={selectedNode}
              repoId={repoId}
              edges={simEdges}
              simNodes={simNodes}
              view={view}
              onClose={() => setSelectedNode(null)}
              onSelect={n => setSelectedNode(n)}
            />
          ) : (
            <HintPanel view={view} nodeCount={graphData.nodes.length} edgeCount={graphData.edges.length} inferredCount={graphData.total_inferred_edges} />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Side panels
// ---------------------------------------------------------------------------

function NodePanel({
  node, repoId, edges, simNodes, view, onClose, onSelect,
}: {
  node: SimNode;
  repoId: string;
  edges: SimEdge[];
  simNodes: SimNode[];
  view: ViewMode;
  onClose: () => void;
  onSelect: (n: SimNode) => void;
}) {
  const nm = new Map(simNodes.map(n => [n.id, n]));
  const outgoing = edges.filter(e => e.source === node.id);
  const incoming = edges.filter(e => e.target === node.id);
  const color = nodeColor(node, view);

  const topNeighbors = [
    ...incoming.map(e => ({ n: nm.get(e.source), dir: "in" as const })),
    ...outgoing.map(e => ({ n: nm.get(e.target), dir: "out" as const })),
  ].filter(x => x.n).slice(0, 5);

  return (
    <div className="rounded-xl border border-white/5 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/[0.02]">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-2.5 w-2.5 rounded shrink-0" style={{ backgroundColor: color }} />
          <span className="text-xs font-semibold text-white truncate">{node.label}</span>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white ml-2 shrink-0">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="p-4 space-y-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">
            {node.type === "cluster" ? "Cluster" : "File"}
          </div>
          <div className="text-xs text-slate-300 font-mono break-all">{node.path}</div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {node.type === "cluster" && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Files</div>
              <div className="text-xs text-slate-300">{node.meta.file_count}</div>
            </div>
          )}
          {node.type === "file" && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Lines</div>
              <div className="text-xs text-slate-300">{node.line_count || "—"}</div>
            </div>
          )}
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Degree</div>
            <div className="text-xs text-slate-300">{node.degree}</div>
          </div>
          {view === "hotspots" && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Risk</div>
              <div className="text-xs font-semibold" style={{ color: nodeColor(node, "hotspots") }}>
                {node.risk_score.toFixed(1)}
              </div>
            </div>
          )}
          {view === "impact" && (
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Status</div>
              <div className="text-xs">
                {node.meta.changed
                  ? <span className="text-rose-400">Changed</span>
                  : node.meta.impacted
                  ? <span className="text-orange-400">Impacted</span>
                  : <span className="text-slate-500">Unaffected</span>}
              </div>
            </div>
          )}
        </div>

        <div className="flex gap-3 text-xs text-slate-400">
          <span className="flex items-center gap-1"><ArrowDownLeft className="h-3 w-3 text-indigo-400" />{incoming.length} in</span>
          <span className="flex items-center gap-1"><ArrowUpRight className="h-3 w-3 text-cyan-400" />{outgoing.length} out</span>
        </div>

        {topNeighbors.length > 0 && (
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1.5">Connected</div>
            <div className="space-y-1">
              {topNeighbors.map(({ n, dir }, i) => {
                const edge = dir === "in"
                  ? edges.find(e => e.source === n?.id && e.target === node.id)
                  : edges.find(e => e.source === node.id && e.target === n?.id);
                const isInferred = edge?.meta?.is_inferred === true
                  || edge?.edge_type === "inferred"
                  || edge?.edge_type === "inferred_naming";
                return n && (
                  <button key={i} onClick={() => onSelect(n)}
                    className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/5 text-left group">
                    <div className="h-1.5 w-1.5 rounded-full shrink-0" style={{ backgroundColor: nodeColor(n, view) }} />
                    <span className="text-xs text-slate-400 group-hover:text-white truncate flex-1 font-mono">{n.label}</span>
                    {isInferred && (
                      <span className="text-[9px] text-slate-600 shrink-0" title="Inferred edge">~</span>
                    )}
                    <span className="text-[9px] text-slate-600">{dir === "in" ? "←" : "→"}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="flex flex-col gap-1.5 pt-2 border-t border-white/5">
          {node.type === "file" ? (
            <>
              <Link href={`/repos/${repoId}/files/${node.id}`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7">
                  <FileCode className="mr-2 h-3.5 w-3.5" /> Open File
                </Button>
              </Link>
              <Link href={`/repos/${repoId}/flows?mode=file&query=${encodeURIComponent(node.path)}`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7 text-indigo-400 hover:text-indigo-300">
                  <Workflow className="mr-2 h-3.5 w-3.5" /> Trace Flow From Here
                </Button>
              </Link>
              <Link href={`/repos/${repoId}/chat`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7">
                  <ChevronRight className="mr-2 h-3.5 w-3.5" /> Ask Repo
                </Button>
              </Link>
            </>
          ) : (
            <>
              <Link href={`/repos/${repoId}/flows?mode=file&query=${encodeURIComponent(node.path)}`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7 text-indigo-400 hover:text-indigo-300">
                  <Workflow className="mr-2 h-3.5 w-3.5" /> Trace Flow From Here
                </Button>
              </Link>
              <Link href={`/repos/${repoId}/impact`}>
                <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7">
                  <Zap className="mr-2 h-3.5 w-3.5" /> PR Impact
                </Button>
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function HintPanel({ view, nodeCount, edgeCount, inferredCount }: {
  view: ViewMode;
  nodeCount: number;
  edgeCount: number;
  inferredCount?: number;
}) {
  return (
    <div className="rounded-xl border border-white/5 bg-slate-900/40 p-4 space-y-4">
      <div>
        <div className="text-xs font-semibold text-white mb-3">
          {VIEW_CONFIG[view].label}
        </div>
        <p className="text-xs text-slate-500 leading-relaxed">{VIEW_CONFIG[view].desc}</p>
      </div>
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Nodes</span>
          <span className="text-slate-300">{nodeCount}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Edges</span>
          <span className="text-slate-300">{edgeCount}</span>
        </div>
        {inferredCount != null && inferredCount > 0 && (
          <div className="flex justify-between text-xs">
            <span className="text-slate-600">Inferred</span>
            <span className="text-slate-500">{inferredCount}</span>
          </div>
        )}
      </div>
      {inferredCount != null && inferredCount > 0 && (
        <div className="flex items-center gap-2 text-[10px] text-slate-600 pt-1">
          <svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#818cf8" strokeWidth="1.5" strokeDasharray="4 3" /></svg>
          <span>dashed = inferred from imports</span>
        </div>
      )}
      <div className="pt-2 border-t border-white/5 space-y-1 text-[11px] text-slate-600">
        <div>Click a node to inspect it</div>
        <div>Hover to highlight connections</div>
        <div>Scroll to zoom · Drag to pan</div>
        {view === "impact" && <div>Enter changed files above and click Analyze</div>}
        {view === "hotspots" && <div>Red = high risk · Orange = medium · Green = low</div>}
      </div>
    </div>
  );
}
