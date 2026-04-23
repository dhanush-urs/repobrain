"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import Link from "next/link";
import type { GraphNode, GraphEdge, RepoGraphData } from "@/lib/types";
import { getRepoGraph } from "@/lib/api";
import {
  Search, X, Filter, ZoomIn, ZoomOut, Maximize2,
  FileCode, GitBranch, AlertCircle, RefreshCw, ChevronRight,
  ArrowUpRight, ArrowDownLeft, Info
} from "lucide-react";
import { Button } from "@/components/common/Button";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx?: number | null;
  fy?: number | null;
}

interface SimEdge extends GraphEdge {
  sourceNode?: SimNode;
  targetNode?: SimNode;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EDGE_COLORS: Record<string, string> = {
  import:      "#6366f1",  // indigo
  from_import: "#8b5cf6",  // violet
  call:        "#06b6d4",  // cyan
  require:     "#f59e0b",  // amber
  export:      "#10b981",  // emerald
};

const EDGE_LABELS: Record<string, string> = {
  import:      "import",
  from_import: "from import",
  call:        "call",
  require:     "require",
  export:      "export",
};

const NODE_COLORS: Record<string, string> = {
  source:    "#6366f1",
  test:      "#f59e0b",
  config:    "#10b981",
  doc:       "#64748b",
  generated: "#374151",
  vendor:    "#374151",
  default:   "#6366f1",
};

const ALL_EDGE_TYPES = ["import", "from_import", "call", "require", "export"];

// ---------------------------------------------------------------------------
// Force-directed layout (simple Verlet integration, no external deps)
// ---------------------------------------------------------------------------

function initLayout(nodes: GraphNode[], edges: GraphEdge[], width: number, height: number): SimNode[] {
  // Place nodes in a circle initially to avoid overlap
  const cx = width / 2;
  const cy = height / 2;
  const r = Math.min(width, height) * 0.35;
  return nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    return {
      ...n,
      x: cx + r * Math.cos(angle) + (Math.random() - 0.5) * 40,
      y: cy + r * Math.sin(angle) + (Math.random() - 0.5) * 40,
      vx: 0,
      vy: 0,
    };
  });
}

function runSimulation(
  nodes: SimNode[],
  edges: SimEdge[],
  width: number,
  height: number,
  iterations: number = 200
): SimNode[] {
  const nodeMap = new Map(nodes.map(n => [n.id, n]));
  const alpha = 0.3;
  const alphaDecay = 0.02;
  const repulsion = 2800;
  const attraction = 0.04;
  const centerForce = 0.008;
  const damping = 0.85;
  const cx = width / 2;
  const cy = height / 2;

  let a = alpha;

  for (let iter = 0; iter < iterations; iter++) {
    a = Math.max(0.001, a * (1 - alphaDecay));

    // Repulsion between all pairs (O(n²) — bounded by max_nodes=120)
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const ni = nodes[i];
        const nj = nodes[j];
        const dx = ni.x - nj.x;
        const dy = ni.y - nj.y;
        const dist2 = dx * dx + dy * dy + 1;
        const dist = Math.sqrt(dist2);
        const force = (repulsion / dist2) * a;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        ni.vx += fx;
        ni.vy += fy;
        nj.vx -= fx;
        nj.vy -= fy;
      }
    }

    // Attraction along edges
    for (const edge of edges) {
      const src = nodeMap.get(edge.source);
      const tgt = nodeMap.get(edge.target);
      if (!src || !tgt) continue;
      const dx = tgt.x - src.x;
      const dy = tgt.y - src.y;
      const dist = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const idealLen = 120 + Math.min(edge.count, 5) * 10;
      const force = (dist - idealLen) * attraction * a;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      src.vx += fx;
      src.vy += fy;
      tgt.vx -= fx;
      tgt.vy -= fy;
    }

    // Center gravity
    for (const n of nodes) {
      n.vx += (cx - n.x) * centerForce * a;
      n.vy += (cy - n.y) * centerForce * a;
    }

    // Integrate + damp
    for (const n of nodes) {
      if (n.fx != null) { n.x = n.fx; n.vx = 0; continue; }
      if (n.fy != null) { n.y = n.fy; n.vy = 0; continue; }
      n.vx *= damping;
      n.vy *= damping;
      n.x += n.vx;
      n.y += n.vy;
      // Boundary
      n.x = Math.max(40, Math.min(width - 40, n.x));
      n.y = Math.max(40, Math.min(height - 40, n.y));
    }
  }

  return nodes;
}

// ---------------------------------------------------------------------------
// Node color helper
// ---------------------------------------------------------------------------

function nodeColor(node: SimNode): string {
  if (node.is_vendor || node.is_generated) return NODE_COLORS.generated;
  if (node.is_test) return NODE_COLORS.test;
  const kind = node.file_kind?.toLowerCase() || "source";
  return NODE_COLORS[kind] || NODE_COLORS.default;
}

function nodeRadius(node: SimNode): number {
  const base = 7;
  const degBonus = Math.min(node.degree * 0.6, 10);
  return base + degBonus;
}


// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type Props = {
  repoId: string;
  initialData: RepoGraphData;
};

export function RepoGraphCanvas({ repoId, initialData }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Graph data state
  const [graphData, setGraphData] = useState<RepoGraphData>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Layout state
  const [simNodes, setSimNodes] = useState<SimNode[]>([]);
  const [simEdges, setSimEdges] = useState<SimEdge[]>([]);
  const [layoutDone, setLayoutDone] = useState(false);

  // Viewport state
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });

  // Interaction state
  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<SimEdge | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeEdgeTypes, setActiveEdgeTypes] = useState<Set<string>>(
    new Set(ALL_EDGE_TYPES)
  );
  const [showNeighborOnly, setShowNeighborOnly] = useState(false);

  const canvasW = 900;
  const canvasH = 620;

  // ── Run layout when graph data changes ──────────────────────────────────
  useEffect(() => {
    if (!graphData.nodes.length) {
      setSimNodes([]);
      setSimEdges([]);
      setLayoutDone(true);
      return;
    }
    setLayoutDone(false);
    const nodes = initLayout(graphData.nodes, graphData.edges, canvasW, canvasH);
    const edges: SimEdge[] = graphData.edges.map(e => ({ ...e }));
    // Run simulation in a microtask to avoid blocking render
    setTimeout(() => {
      const laid = runSimulation(nodes, edges, canvasW, canvasH, 250);
      const nodeMap = new Map(laid.map(n => [n.id, n]));
      const simE = edges.map(e => ({
        ...e,
        sourceNode: nodeMap.get(e.source),
        targetNode: nodeMap.get(e.target),
      }));
      setSimNodes(laid);
      setSimEdges(simE);
      setLayoutDone(true);
    }, 0);
  }, [graphData]);

  // ── Filtered edges by active types ──────────────────────────────────────
  const visibleEdges = useMemo(() =>
    simEdges.filter(e => activeEdgeTypes.has(e.edge_type)),
    [simEdges, activeEdgeTypes]
  );

  // ── Neighbor set for selected node ──────────────────────────────────────
  const neighborIds = useMemo(() => {
    if (!selectedNode) return new Set<string>();
    const ids = new Set<string>();
    for (const e of visibleEdges) {
      if (e.source === selectedNode.id) ids.add(e.target);
      if (e.target === selectedNode.id) ids.add(e.source);
    }
    return ids;
  }, [selectedNode, visibleEdges]);

  // ── Search filter ────────────────────────────────────────────────────────
  const searchMatches = useMemo(() => {
    if (!searchQuery.trim()) return new Set<string>();
    const q = searchQuery.toLowerCase();
    return new Set(simNodes.filter(n => n.path.toLowerCase().includes(q)).map(n => n.id));
  }, [simNodes, searchQuery]);

  // ── Node visibility ──────────────────────────────────────────────────────
  const isNodeVisible = useCallback((node: SimNode) => {
    if (searchQuery.trim() && !searchMatches.has(node.id)) return false;
    if (showNeighborOnly && selectedNode) {
      return node.id === selectedNode.id || neighborIds.has(node.id);
    }
    return true;
  }, [searchQuery, searchMatches, showNeighborOnly, selectedNode, neighborIds]);

  // ── Pan handlers ─────────────────────────────────────────────────────────
  const onMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(".graph-node, .graph-edge")) return;
    isPanning.current = true;
    panStart.current = { x: e.clientX, y: e.clientY, tx: transform.x, ty: transform.y };
    e.preventDefault();
  }, [transform]);

  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!isPanning.current) return;
    const dx = e.clientX - panStart.current.x;
    const dy = e.clientY - panStart.current.y;
    setTransform(t => ({ ...t, x: panStart.current.tx + dx, y: panStart.current.ty + dy }));
  }, []);

  const onMouseUp = useCallback(() => { isPanning.current = false; }, []);

  const onWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 0.89;
    setTransform(t => ({
      ...t,
      scale: Math.max(0.15, Math.min(4, t.scale * factor)),
    }));
  }, []);

  const fitView = useCallback(() => {
    if (!simNodes.length) return;
    const xs = simNodes.map(n => n.x);
    const ys = simNodes.map(n => n.y);
    const minX = Math.min(...xs) - 40;
    const maxX = Math.max(...xs) + 40;
    const minY = Math.min(...ys) - 40;
    const maxY = Math.max(...ys) + 40;
    const scaleX = canvasW / (maxX - minX);
    const scaleY = canvasH / (maxY - minY);
    const scale = Math.min(scaleX, scaleY, 2);
    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    setTransform({
      scale,
      x: canvasW / 2 - cx * scale,
      y: canvasH / 2 - cy * scale,
    });
  }, [simNodes]);

  // ── Reload with different params ─────────────────────────────────────────
  const reload = useCallback(async (edgeTypes?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getRepoGraph(repoId, {
        edge_types: edgeTypes || Array.from(activeEdgeTypes).join(","),
        max_nodes: 120,
        min_degree: 1,
      });
      setGraphData(data);
    } catch (e) {
      setError("Failed to load graph data.");
    } finally {
      setLoading(false);
    }
  }, [repoId, activeEdgeTypes]);

  // ── Toggle edge type ─────────────────────────────────────────────────────
  const toggleEdgeType = useCallback((type: string) => {
    setActiveEdgeTypes(prev => {
      const next = new Set(prev);
      if (next.has(type)) {
        if (next.size > 1) next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }, []);

  // ── Empty / error states ─────────────────────────────────────────────────
  const hasNoData = graphData.nodes.length === 0;
  const hasNoEdges = graphData.total_resolved_edges === 0;

  if (hasNoData || hasNoEdges) {
    return (
      <div className="rounded-xl border border-white/5 bg-slate-900/30 p-12 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-slate-900 text-slate-500 ring-1 ring-white/10">
          <GitBranch className="h-7 w-7" />
        </div>
        <h3 className="text-base font-semibold text-white mb-2">
          {hasNoData ? "No indexed files found" : "No resolved file relationships"}
        </h3>
        <p className="text-sm text-slate-400 max-w-sm mx-auto leading-relaxed mb-6">
          {hasNoData
            ? "Index this repository first to generate the file relationship graph."
            : "The graph requires parsed and indexed files with resolved import/call edges. Re-index the repository to populate relationships."}
        </p>
        <Link href={`/repos/${repoId}/refresh-jobs`}>
          <Button variant="outline" size="sm">
            <RefreshCw className="mr-2 h-4 w-4" />
            View Refresh Jobs
          </Button>
        </Link>
      </div>
    );
  }

  const totalVisible = simNodes.filter(isNodeVisible).length;

  return (
    <div className="flex flex-col gap-4">
      {/* Stats bar */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
          {graphData.nodes.length} files
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-slate-600" />
          {visibleEdges.length} relationships
        </span>
        {graphData.truncated && (
          <span className="text-amber-400/70 flex items-center gap-1">
            <Info className="h-3 w-3" />
            Showing top {graphData.nodes.length} files by connectivity
          </span>
        )}
        {graphData.total_files > graphData.nodes.length && (
          <span className="text-slate-600">
            ({graphData.total_files} total files in repo)
          </span>
        )}
      </div>

      <div className="flex gap-4 items-start">
        {/* Main graph area */}
        <div className="flex-1 min-w-0">
          {/* Toolbar */}
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {/* Search */}
            <div className="relative flex-1 min-w-[180px] max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-500" />
              <input
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search files..."
                className="w-full pl-9 pr-3 h-8 rounded-lg bg-slate-900 border border-white/10 text-sm text-slate-200 placeholder:text-slate-600 outline-none focus:border-indigo-500/50 transition-colors"
              />
              {searchQuery && (
                <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            {/* Edge type filters */}
            <div className="flex items-center gap-1">
              {ALL_EDGE_TYPES.filter(t => (graphData.edge_type_counts[t] || 0) > 0).map(type => (
                <button
                  key={type}
                  onClick={() => toggleEdgeType(type)}
                  className={cn(
                    "h-7 px-2.5 rounded-md text-[10px] font-semibold uppercase tracking-wide transition-all border",
                    activeEdgeTypes.has(type)
                      ? "text-white border-transparent"
                      : "text-slate-600 border-white/5 bg-transparent"
                  )}
                  style={activeEdgeTypes.has(type) ? {
                    backgroundColor: EDGE_COLORS[type] + "22",
                    borderColor: EDGE_COLORS[type] + "44",
                    color: EDGE_COLORS[type],
                  } : {}}
                  title={`${EDGE_LABELS[type]} (${graphData.edge_type_counts[type] || 0})`}
                >
                  {type === "from_import" ? "from" : type}
                </button>
              ))}
            </div>

            {/* Neighbor toggle */}
            {selectedNode && (
              <button
                onClick={() => setShowNeighborOnly(v => !v)}
                className={cn(
                  "h-7 px-2.5 rounded-md text-[10px] font-semibold uppercase tracking-wide transition-all border",
                  showNeighborOnly
                    ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-400"
                    : "border-white/5 text-slate-500 hover:text-white"
                )}
              >
                Neighbors only
              </button>
            )}

            <div className="ml-auto flex items-center gap-1">
              <button onClick={() => setTransform(t => ({ ...t, scale: Math.min(4, t.scale * 1.2) }))}
                className="h-7 w-7 flex items-center justify-center rounded-lg border border-white/5 text-slate-400 hover:text-white hover:bg-white/5 transition-colors">
                <ZoomIn className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => setTransform(t => ({ ...t, scale: Math.max(0.15, t.scale * 0.83) }))}
                className="h-7 w-7 flex items-center justify-center rounded-lg border border-white/5 text-slate-400 hover:text-white hover:bg-white/5 transition-colors">
                <ZoomOut className="h-3.5 w-3.5" />
              </button>
              <button onClick={fitView}
                className="h-7 w-7 flex items-center justify-center rounded-lg border border-white/5 text-slate-400 hover:text-white hover:bg-white/5 transition-colors">
                <Maximize2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* SVG Canvas */}
          <div
            ref={containerRef}
            className="relative rounded-xl border border-white/5 bg-slate-950/60 overflow-hidden"
            style={{ height: canvasH }}
          >
            {(loading || !layoutDone) && (
              <div className="absolute inset-0 flex items-center justify-center bg-slate-950/60 z-10">
                <div className="flex items-center gap-2 text-sm text-slate-400">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  {loading ? "Loading graph…" : "Computing layout…"}
                </div>
              </div>
            )}

            <svg
              ref={svgRef}
              width={canvasW}
              height={canvasH}
              className="w-full h-full cursor-grab active:cursor-grabbing select-none"
              onMouseDown={onMouseDown}
              onMouseMove={onMouseMove}
              onMouseUp={onMouseUp}
              onMouseLeave={onMouseUp}
              onWheel={onWheel}
            >
              <defs>
                {ALL_EDGE_TYPES.map(type => (
                  <marker
                    key={type}
                    id={`arrow-${type}`}
                    markerWidth="6"
                    markerHeight="6"
                    refX="5"
                    refY="3"
                    orient="auto"
                  >
                    <path d="M0,0 L0,6 L6,3 z" fill={EDGE_COLORS[type] || "#6366f1"} opacity="0.6" />
                  </marker>
                ))}
              </defs>

              <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
                {/* Edges */}
                {layoutDone && visibleEdges.map(edge => {
                  const src = edge.sourceNode;
                  const tgt = edge.targetNode;
                  if (!src || !tgt) return null;
                  const srcVisible = isNodeVisible(src);
                  const tgtVisible = isNodeVisible(tgt);
                  if (!srcVisible || !tgtVisible) return null;

                  const isHighlighted = hoveredNode === src.id || hoveredNode === tgt.id
                    || selectedNode?.id === src.id || selectedNode?.id === tgt.id;
                  const isSelected = selectedEdge?.id === edge.id;
                  const color = EDGE_COLORS[edge.edge_type] || "#6366f1";
                  const opacity = isHighlighted || isSelected ? 0.85 : 0.18;
                  const strokeW = isSelected ? 2.5 : isHighlighted ? 1.8 : Math.min(1 + edge.count * 0.3, 3);

                  // Offset for parallel edges
                  const dx = tgt.x - src.x;
                  const dy = tgt.y - src.y;
                  const len = Math.sqrt(dx * dx + dy * dy) || 1;
                  const nx = -dy / len * 4;
                  const ny = dx / len * 4;

                  return (
                    <line
                      key={edge.id}
                      className="graph-edge"
                      x1={src.x + nx}
                      y1={src.y + ny}
                      x2={tgt.x + nx}
                      y2={tgt.y + ny}
                      stroke={color}
                      strokeWidth={strokeW}
                      strokeOpacity={opacity}
                      markerEnd={`url(#arrow-${edge.edge_type})`}
                      style={{ cursor: "pointer", transition: "stroke-opacity 0.15s" }}
                      onClick={e => { e.stopPropagation(); setSelectedEdge(edge); setSelectedNode(null); }}
                    />
                  );
                })}

                {/* Nodes */}
                {layoutDone && simNodes.map(node => {
                  if (!isNodeVisible(node)) return null;
                  const r = nodeRadius(node);
                  const color = nodeColor(node);
                  const isSelected = selectedNode?.id === node.id;
                  const isHovered = hoveredNode === node.id;
                  const isNeighbor = neighborIds.has(node.id);
                  const isSearchMatch = searchQuery.trim() ? searchMatches.has(node.id) : false;
                  const dimmed = (selectedNode && !isSelected && !isNeighbor)
                    || (searchQuery.trim() && !isSearchMatch);

                  return (
                    <g
                      key={node.id}
                      className="graph-node"
                      transform={`translate(${node.x},${node.y})`}
                      style={{ cursor: "pointer" }}
                      onClick={e => {
                        e.stopPropagation();
                        setSelectedNode(isSelected ? null : node);
                        setSelectedEdge(null);
                        setShowNeighborOnly(false);
                      }}
                      onMouseEnter={() => setHoveredNode(node.id)}
                      onMouseLeave={() => setHoveredNode(null)}
                    >
                      {/* Glow ring for selected/hovered */}
                      {(isSelected || isHovered) && (
                        <circle
                          r={r + 5}
                          fill="none"
                          stroke={color}
                          strokeWidth={isSelected ? 2 : 1}
                          strokeOpacity={0.4}
                        />
                      )}
                      {/* Main circle */}
                      <circle
                        r={r}
                        fill={color}
                        fillOpacity={dimmed ? 0.15 : isSelected ? 1 : isNeighbor ? 0.85 : 0.7}
                        stroke={isSelected ? color : "rgba(255,255,255,0.15)"}
                        strokeWidth={isSelected ? 2 : 1}
                        style={{ transition: "fill-opacity 0.15s" }}
                      />
                      {/* Label — only show when not too zoomed out */}
                      {transform.scale > 0.5 && (
                        <text
                          y={r + 11}
                          textAnchor="middle"
                          fontSize={transform.scale > 1 ? 9 : 8}
                          fill={dimmed ? "rgba(255,255,255,0.2)" : "rgba(255,255,255,0.75)"}
                          style={{ pointerEvents: "none", userSelect: "none" }}
                        >
                          {node.name.length > 18 ? node.name.slice(0, 16) + "…" : node.name}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>

            {/* Legend */}
            <div className="absolute bottom-3 left-3 flex flex-wrap gap-2">
              {ALL_EDGE_TYPES.filter(t => activeEdgeTypes.has(t) && (graphData.edge_type_counts[t] || 0) > 0).map(type => (
                <div key={type} className="flex items-center gap-1.5 text-[10px] text-slate-500">
                  <div className="h-1.5 w-4 rounded-full" style={{ backgroundColor: EDGE_COLORS[type] }} />
                  {EDGE_LABELS[type]}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Details panel */}
        <div className="w-72 shrink-0 space-y-3">
          {selectedNode ? (
            <NodeDetailPanel
              node={selectedNode}
              repoId={repoId}
              edges={visibleEdges}
              simNodes={simNodes}
              onClose={() => { setSelectedNode(null); setShowNeighborOnly(false); }}
              onSelectNode={n => { setSelectedNode(n); setShowNeighborOnly(false); }}
            />
          ) : selectedEdge ? (
            <EdgeDetailPanel
              edge={selectedEdge}
              simNodes={simNodes}
              repoId={repoId}
              onClose={() => setSelectedEdge(null)}
              onSelectNode={n => { setSelectedNode(n); setSelectedEdge(null); }}
            />
          ) : (
            <GraphHintPanel
              nodeCount={graphData.nodes.length}
              edgeCount={visibleEdges.length}
              edgeTypeCounts={graphData.edge_type_counts}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-panels
// ---------------------------------------------------------------------------

function NodeDetailPanel({
  node, repoId, edges, simNodes, onClose, onSelectNode,
}: {
  node: SimNode;
  repoId: string;
  edges: SimEdge[];
  simNodes: SimNode[];
  onClose: () => void;
  onSelectNode: (n: SimNode) => void;
}) {
  const outgoing = edges.filter(e => e.source === node.id);
  const incoming = edges.filter(e => e.target === node.id);
  const nodeMap = new Map(simNodes.map(n => [n.id, n]));

  const topNeighbors = [
    ...incoming.map(e => ({ node: nodeMap.get(e.source), dir: "in" as const, type: e.edge_type })),
    ...outgoing.map(e => ({ node: nodeMap.get(e.target), dir: "out" as const, type: e.edge_type })),
  ]
    .filter(x => x.node)
    .slice(0, 6);

  const color = nodeColor(node);

  return (
    <div className="rounded-xl border border-white/5 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/[0.02]">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
          <span className="text-xs font-semibold text-white truncate">{node.name}</span>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white ml-2 shrink-0">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {/* Path */}
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Path</div>
          <div className="text-xs text-slate-300 font-mono break-all leading-relaxed">{node.path}</div>
        </div>

        {/* Meta */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Language</div>
            <div className="text-xs text-slate-300">{node.language || "—"}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Kind</div>
            <div className="text-xs text-slate-300 capitalize">{node.file_kind}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Lines</div>
            <div className="text-xs text-slate-300">{node.line_count || "—"}</div>
          </div>
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-0.5">Degree</div>
            <div className="text-xs text-slate-300">{node.degree}</div>
          </div>
        </div>

        {/* Edge counts */}
        <div className="flex gap-4">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <ArrowDownLeft className="h-3.5 w-3.5 text-indigo-400" />
            {incoming.length} incoming
          </div>
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <ArrowUpRight className="h-3.5 w-3.5 text-cyan-400" />
            {outgoing.length} outgoing
          </div>
        </div>

        {/* Top neighbors */}
        {topNeighbors.length > 0 && (
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">Connected Files</div>
            <div className="space-y-1">
              {topNeighbors.map(({ node: n, dir, type }, i) => n && (
                <button
                  key={i}
                  onClick={() => onSelectNode(n)}
                  className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/5 transition-colors text-left group"
                >
                  <div
                    className="h-1.5 w-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: EDGE_COLORS[type] || "#6366f1" }}
                  />
                  <span className="text-xs text-slate-400 group-hover:text-white truncate flex-1 font-mono">
                    {n.name}
                  </span>
                  <span className="text-[9px] text-slate-600 shrink-0">
                    {dir === "in" ? "←" : "→"}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-col gap-2 pt-1 border-t border-white/5">
          <Link href={`/repos/${repoId}/files`} className="w-full">
            <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-8">
              <FileCode className="mr-2 h-3.5 w-3.5" />
              Open in File Explorer
            </Button>
          </Link>
          <Link href={`/repos/${repoId}/chat`} className="w-full">
            <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-8">
              <ChevronRight className="mr-2 h-3.5 w-3.5" />
              Ask about this file
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}

function EdgeDetailPanel({
  edge, simNodes, repoId, onClose, onSelectNode,
}: {
  edge: SimEdge;
  simNodes: SimNode[];
  repoId: string;
  onClose: () => void;
  onSelectNode: (n: SimNode) => void;
}) {
  const nodeMap = new Map(simNodes.map(n => [n.id, n]));
  const src = nodeMap.get(edge.source);
  const tgt = nodeMap.get(edge.target);
  const color = EDGE_COLORS[edge.edge_type] || "#6366f1";

  return (
    <div className="rounded-xl border border-white/5 bg-slate-900/60 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/[0.02]">
        <div className="flex items-center gap-2">
          <div className="h-2 w-4 rounded-full" style={{ backgroundColor: color }} />
          <span className="text-xs font-semibold text-white capitalize">{EDGE_LABELS[edge.edge_type]}</span>
          {edge.count > 1 && (
            <span className="text-[10px] text-slate-500">×{edge.count}</span>
          )}
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-white">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="p-4 space-y-3">
        {src && (
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Source</div>
            <button
              onClick={() => onSelectNode(src)}
              className="text-xs text-slate-300 font-mono hover:text-indigo-400 transition-colors text-left break-all"
            >
              {src.path}
            </button>
          </div>
        )}
        {tgt && (
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-1">Target</div>
            <button
              onClick={() => onSelectNode(tgt)}
              className="text-xs text-slate-300 font-mono hover:text-indigo-400 transition-colors text-left break-all"
            >
              {tgt.path}
            </button>
          </div>
        )}
        <div className="flex gap-4 pt-1 border-t border-white/5">
          {src && (
            <Link href={`/repos/${repoId}/files`}>
              <Button variant="ghost" size="sm" className="text-xs h-7">
                Open source
              </Button>
            </Link>
          )}
          {tgt && (
            <Link href={`/repos/${repoId}/files`}>
              <Button variant="ghost" size="sm" className="text-xs h-7">
                Open target
              </Button>
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

function GraphHintPanel({
  nodeCount, edgeCount, edgeTypeCounts,
}: {
  nodeCount: number;
  edgeCount: number;
  edgeTypeCounts: Record<string, number>;
}) {
  return (
    <div className="rounded-xl border border-white/5 bg-slate-900/40 p-4 space-y-4">
      <div>
        <div className="text-xs font-semibold text-white mb-3">Graph Overview</div>
        <div className="space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">Files</span>
            <span className="text-slate-300 font-medium">{nodeCount}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">Relationships</span>
            <span className="text-slate-300 font-medium">{edgeCount}</span>
          </div>
        </div>
      </div>

      {Object.keys(edgeTypeCounts).length > 0 && (
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-500 mb-2">By Type</div>
          <div className="space-y-1.5">
            {Object.entries(edgeTypeCounts)
              .sort((a, b) => b[1] - a[1])
              .map(([type, count]) => (
                <div key={type} className="flex items-center gap-2">
                  <div className="h-1.5 w-1.5 rounded-full shrink-0" style={{ backgroundColor: EDGE_COLORS[type] || "#6366f1" }} />
                  <span className="text-xs text-slate-500 flex-1 capitalize">{EDGE_LABELS[type] || type}</span>
                  <span className="text-xs text-slate-400 font-medium">{count}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      <div className="pt-2 border-t border-white/5 space-y-1.5 text-[11px] text-slate-600">
        <div>Click a node to inspect it</div>
        <div>Hover to highlight connections</div>
        <div>Scroll to zoom · Drag to pan</div>
        <div>Use filters to focus edge types</div>
      </div>
    </div>
  );
}
