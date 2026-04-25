"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { FlowData, FlowNode, FlowEdge, FlowPath } from "@/lib/types";
import { getExecutionFlow } from "@/lib/api";
import {
  Workflow, Search, RefreshCw, AlertCircle, Info,
  ChevronRight, X, GitBranch, Zap, FileCode,
  ArrowRight, Loader2
} from "lucide-react";
import { Button } from "@/components/common/Button";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type FlowMode = "primary" | "route" | "file" | "function" | "impact";

interface LayoutNode extends FlowNode {
  x: number;
  y: number;
}

// ---------------------------------------------------------------------------
// Node visual config
// ---------------------------------------------------------------------------

const NODE_TYPE_COLORS: Record<string, string> = {
  route_handler:   "#6366f1",  // indigo
  service:         "#8b5cf6",  // violet
  repository:      "#06b6d4",  // cyan
  model:           "#10b981",  // emerald
  utility:         "#64748b",  // slate
  middleware:      "#f59e0b",  // amber
  worker:          "#f97316",  // orange
  external_client: "#ec4899",  // pink
  config:          "#64748b",  // slate
  module:          "#6366f1",  // indigo fallback
  // Frontend node types
  frontend:        "#f59e0b",  // amber
  frontend_view:   "#f59e0b",  // amber
  frontend_component: "#f59e0b",
  frontend_api_client: "#f97316",
  // Data / config
  data:            "#10b981",  // emerald
  integration:     "#ec4899",  // pink
};

const NODE_TYPE_LABELS: Record<string, string> = {
  route_handler:   "Route",
  service:         "Service",
  repository:      "Repository",
  model:           "Model",
  utility:         "Utility",
  middleware:      "Middleware",
  worker:          "Worker",
  external_client: "External",
  config:          "Config",
  module:          "Module",
  frontend:        "Frontend",
  frontend_view:   "Frontend",
  frontend_component: "Component",
  frontend_api_client: "API Client",
  data:            "Data",
  integration:     "Integration",
};

const MODE_CONFIG: Record<FlowMode, { label: string; placeholder: string; inputLabel: string }> = {
  primary:  { label: "Primary Flow",  placeholder: "",                                inputLabel: "Entrypoint hint (optional)" },
  route:    { label: "Route Flow",    placeholder: "/login  or  /api/users",         inputLabel: "Route path" },
  file:     { label: "File Flow",     placeholder: "app/services/auth.py",           inputLabel: "File path" },
  function: { label: "Function Flow", placeholder: "authenticate_user",              inputLabel: "Function name" },
  impact:   { label: "Impact Flow",   placeholder: "app/api/routes.py,app/auth.py",  inputLabel: "Changed files (comma-separated)" },
};

// ---------------------------------------------------------------------------
// Layered left-to-right layout — semantic role-aware
// ---------------------------------------------------------------------------

// Semantic layer order: lower index = further left (upstream)
const _ROLE_LAYER: Record<string, number> = {
  // Frontend / entry (leftmost)
  frontend_view: 0, frontend_component: 0, frontend_api_client: 0, frontend: 0,
  // Entrypoint
  entrypoint: 1,
  // Route / middleware
  route_handler: 2, middleware: 2,
  // Service / business logic
  service: 3,
  // Data / persistence
  repository: 4, model: 4, data: 4,
  // Config / integration / external (rightmost)
  config: 5, integration: 5, external_client: 5,
  worker: 5, utility: 6,
  module: 3,  // fallback: middle
};

function _roleLayer(nodeType: string): number {
  return _ROLE_LAYER[nodeType] ?? 3;
}

function layoutNodesLayered(nodes: FlowNode[], W: number, H: number): LayoutNode[] {
  if (!nodes.length) return [];

  // Assign each node to a semantic layer based on its type/role
  const layerMap = new Map<number, FlowNode[]>();
  for (const n of nodes) {
    const layer = _roleLayer(n.type);
    if (!layerMap.has(layer)) layerMap.set(layer, []);
    layerMap.get(layer)!.push(n);
  }

  // If all nodes ended up in the same layer (no role diversity), fall back to sequential
  const usedLayers = Array.from(layerMap.keys()).sort((a, b) => a - b);
  const effectiveLayers: FlowNode[][] = usedLayers.length > 1
    ? usedLayers.map(l => layerMap.get(l)!)
    : nodes.map(n => [n]);  // sequential fallback

  const numLayers = effectiveLayers.length;
  const layerW = W / (numLayers + 1);

  const result: LayoutNode[] = [];
  effectiveLayers.forEach((layer, layerIdx) => {
    const x = layerW * (layerIdx + 1);
    const layerH = H / (layer.length + 1);
    layer.forEach((n, nodeIdx) => {
      result.push({
        ...n,
        x,
        y: layerH * (nodeIdx + 1),
      });
    });
  });

  return result;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type Props = {
  repoId: string;
  initialMode: FlowMode;
  initialQuery: string;
  initialChanged: string;
};

export function FlowCanvas({ repoId, initialMode, initialQuery, initialChanged }: Props) {
  const [mode, setMode] = useState<FlowMode>(initialMode);
  const [queryInput, setQueryInput] = useState(
    initialMode === "impact" ? initialChanged : initialQuery
  );
  const [loading, setLoading] = useState(false);
  const [flowData, setFlowData] = useState<FlowData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedPathIdx, setSelectedPathIdx] = useState(0);
  const [selectedNode, setSelectedNode] = useState<LayoutNode | null>(null);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const isPanning = useRef(false);
  const panStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });
  const reqSeq = useRef(0);

  const W = 820, H = 480;

  const runFlow = useCallback(async (m: FlowMode, q: string) => {
    // primary mode runs with empty query (auto-detect)
    if (m !== "primary" && !q.trim()) return;
    reqSeq.current += 1;
    const seq = reqSeq.current;
    setLoading(true); setError(null); setFlowData(null); setSelectedNode(null); setSelectedPathIdx(0);
    try {
      const data = await getExecutionFlow(repoId, {
        mode: m,
        query: m !== "impact" ? q : undefined,
        changed: m === "impact" ? q : undefined,
        depth: 4,
      });
      if (seq !== reqSeq.current) return;
      setFlowData(data);
    } catch {
      if (seq !== reqSeq.current) return;
      setError("Failed to load flow data.");
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [repoId]);

  // Auto-trigger on mount:
  // - If URL has explicit mode+query params, use those
  // - Otherwise always run primary mode (no input needed)
  useEffect(() => {
    if (initialQuery || initialChanged) {
      runFlow(initialMode, initialMode === "impact" ? initialChanged : initialQuery);
    } else {
      // Default: auto-render primary app flow
      runFlow("primary", "");
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    runFlow(mode, queryInput);
  };

  // Current path — use layered layout
  const currentPath: FlowPath | null = flowData?.paths?.[selectedPathIdx] ?? null;
  const layoutNodes_ = currentPath ? layoutNodesLayered(currentPath.nodes, W, H) : [];
  const nodeMap = new Map(layoutNodes_.map(n => [n.id, n]));

  // Pan
  const onMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(".flow-node")) return;
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
    setTransform(t => ({ ...t, scale: Math.max(0.2, Math.min(3, t.scale * (e.deltaY < 0 ? 1.12 : 0.89))) }));
  }, []);

  const isEmpty = !flowData || flowData.paths.length === 0;

  return (
    <div className="flex flex-col gap-5">
      {/* Mode selector + input */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {/* Primary tab — always first */}
          <button
            onClick={() => { setMode("primary"); setQueryInput(""); setFlowData(null); setError(null); setSelectedNode(null); runFlow("primary", ""); }}
            className={cn(
              "flex items-center gap-2 h-8 px-3 rounded-md text-[11px] font-semibold transition-all border",
              mode === "primary"
                ? "bg-indigo-500/10 border-indigo-500/20 text-indigo-400"
                : "border-white/5 text-slate-500 hover:text-slate-300 hover:bg-white/5"
            )}
          >
            <Workflow size={14} />
            Primary Flow
          </button>

          {/* Divider */}
          <span className="text-slate-800 text-xs">|</span>

          {/* Advanced manual modes */}
          {(["route", "file", "function", "impact"] as FlowMode[]).map(m => {
            const cfg = MODE_CONFIG[m];
            return (
              <button
                key={m}
                onClick={() => { setMode(m); setQueryInput(""); setFlowData(null); setError(null); setSelectedNode(null); }}
                className={cn(
                  "flex items-center gap-2 h-8 px-3 rounded-md text-[11px] font-semibold transition-all border",
                  mode === m
                    ? "bg-indigo-500/10 border-indigo-500/20 text-indigo-400"
                    : "border-white/5 text-slate-500 hover:text-slate-300 hover:bg-white/5"
                )}
              >
                {m === "route" && <ArrowRight size={14} />}
                {m === "file" && <FileCode size={14} />}
                {m === "function" && <Search size={14} />}
                {m === "impact" && <Zap size={14} />}
                {cfg.label}
              </button>
            );
          })}
        </div>

        {/* Input row — hidden for primary mode (no input needed) */}
        {mode !== "primary" && (
          <form onSubmit={onSubmit} className="flex items-end gap-3 max-w-2xl">
            <div className="flex-1 space-y-1.5">
              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-600 block px-1">
                {MODE_CONFIG[mode].inputLabel}
              </label>
              <input
                value={queryInput}
                onChange={e => setQueryInput(e.target.value)}
                placeholder={MODE_CONFIG[mode].placeholder}
                className="w-full h-9 px-3 rounded-md bg-slate-900 border border-white/10 text-[13px] text-slate-200 placeholder:text-slate-700 outline-none focus:border-indigo-500/40 transition-colors font-mono shadow-inner"
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={loading || !queryInput.trim()}
              isLoading={loading}
              className="h-9 px-6"
            >
              <Workflow size={14} className="mr-2" />
              Trace
            </Button>
          </form>
        )}

        {/* Entrypoint selector — shown in primary mode when multiple candidates exist */}
        {mode === "primary" && flowData?.entrypoint_candidates && flowData.entrypoint_candidates.length > 1 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">Entrypoint:</span>
            {flowData.entrypoint_candidates.map(ep => (
              <button
                key={ep.path}
                onClick={() => runFlow("primary", ep.path)}
                className={cn(
                  "h-7 px-2.5 rounded-lg text-xs font-mono transition-all border",
                  flowData.selected_entrypoint === ep.path
                    ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300"
                    : "border-white/5 text-slate-500 hover:text-white hover:bg-white/5"
                )}
              >
                {ep.name}
                <span className="ml-1.5 text-[9px] opacity-60">{Math.round(ep.confidence * 100)}%</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-sm text-rose-400">
          <AlertCircle className="h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center gap-2 text-sm text-slate-400 py-4">
          <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
          Inferring execution flow…
        </div>
      )}

      {/* Results */}
      {flowData && !loading && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-500">
          {/* Summary strip */}
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {/* Mode chip */}
            <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-indigo-400">
              {MODE_CONFIG[mode].label}
            </span>
            {/* Entrypoint chip (primary mode) */}
            {mode === "primary" && flowData.selected_entrypoint && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-mono text-slate-400 max-w-[220px] truncate">
                {flowData.selected_entrypoint.split("/").pop()}
              </span>
            )}
            {/* Query chip (non-primary modes) */}
            {mode !== "primary" && queryInput && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] font-mono text-slate-400 max-w-[200px] truncate">
                {queryInput}
              </span>
            )}
            {/* Paths */}
            <span className="inline-flex items-center gap-1 rounded-full border border-white/5 bg-white/[0.02] px-2.5 py-1 text-[10px] text-slate-500">
              {flowData.summary.path_count} path{flowData.summary.path_count !== 1 ? "s" : ""}
            </span>
            {/* Nodes */}
            {currentPath && (
              <span className="inline-flex items-center gap-1 rounded-full border border-white/5 bg-white/[0.02] px-2.5 py-1 text-[10px] text-slate-500">
                {currentPath.nodes.length} nodes · {currentPath.edges.length} edges
              </span>
            )}
            {/* Confidence */}
            <span className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-semibold",
              flowData.summary.estimated_confidence >= 0.7
                ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
                : flowData.summary.estimated_confidence >= 0.4
                ? "border-amber-500/20 bg-amber-500/10 text-amber-400"
                : "border-slate-500/20 bg-slate-500/10 text-slate-400"
            )}>
              {Math.round(flowData.summary.estimated_confidence * 100)}% confidence
            </span>
            {/* Notes */}
            {flowData.summary.notes.length > 0 && (
              <span className="inline-flex items-center gap-1 text-[10px] text-slate-600">
                <Info className="h-3 w-3" />
                {flowData.summary.notes[0]}
              </span>
            )}
            <Link href={`/repos/${repoId}/graph`} className="ml-auto">
              <Button variant="ghost" size="sm" className="text-xs h-7">
                <GitBranch className="mr-1.5 h-3.5 w-3.5" />
                Knowledge Graph
              </Button>
            </Link>
          </div>

          {/* Path tabs */}
          {flowData.paths.length > 1 && (
            <div className="flex gap-1.5 mb-3">
              {flowData.paths.map((p, i) => (
                <button
                  key={p.id}
                  onClick={() => { setSelectedPathIdx(i); setSelectedNode(null); }}
                  className={cn(
                    "h-7 px-3 rounded-lg text-xs font-medium transition-all border",
                    selectedPathIdx === i
                      ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-300"
                      : "border-white/5 text-slate-500 hover:text-white hover:bg-white/5"
                  )}
                >
                  Path {i + 1}
                  <span className="ml-1.5 text-[10px] opacity-60">{Math.round(p.score * 100)}%</span>
                </button>
              ))}
            </div>
          )}

          {/* No paths */}
          {isEmpty && (
            <div className="rounded-xl border border-white/5 bg-slate-900/30 p-10 text-center">
              <Workflow className="h-8 w-8 text-slate-600 mx-auto mb-3" />
              <p className="text-sm font-semibold text-white mb-1">No flow paths found</p>
              <p className="text-xs text-slate-400 max-w-sm mx-auto mb-4">
                {mode === "primary"
                  ? "Could not detect a clear application entrypoint. Try File Flow with a specific file path."
                  : (flowData.summary.notes[0] || "Try a different query or ensure the repository is indexed.")}
              </p>
              {mode === "primary" && (
                <Button
                  variant="outline" size="sm"
                  onClick={() => { setMode("file"); setFlowData(null); }}
                >
                  <FileCode className="mr-2 h-3.5 w-3.5" />
                  Switch to File Flow
                </Button>
              )}
            </div>
          )}

          {/* Flow canvas + panel */}
          {currentPath && (
            <div className="flex gap-4 items-start animate-in fade-in duration-500">
              <div className="flex-1 min-w-0">
                {/* Path explanation */}
                <p className="text-xs text-slate-500 mb-3 leading-relaxed border-l-2 border-indigo-500/30 pl-3">
                  {currentPath.explanation}
                </p>

                {/* SVG canvas */}
                <div className="relative rounded-xl border border-white/5 bg-slate-950/60 overflow-hidden" style={{ height: H }}>
                  <svg
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
                      <marker id="flow-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                        <path d="M0,0 L0,8 L8,4 z" fill="rgba(99,102,241,0.7)" />
                      </marker>
                    </defs>

                    <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
                      {/* Edges */}
                      {currentPath.edges.map((edge, i) => {
                        const s = nodeMap.get(edge.source);
                        const t = nodeMap.get(edge.target);
                        if (!s || !t) return null;
                        const dx = t.x - s.x, dy = t.y - s.y;
                        const len = Math.sqrt(dx * dx + dy * dy) || 1;
                        // Shorten line to node boundary
                        const nr = 36;
                        const x1 = s.x + (dx / len) * nr;
                        const y1 = s.y + (dy / len) * nr;
                        const x2 = t.x - (dx / len) * (nr + 4);
                        const y2 = t.y - (dy / len) * (nr + 4);
                        // Semantic edge label
                        const _EDGE_LABELS: Record<string, string> = {
                          route_to_service: "calls service",
                          service_to_model: "uses model",
                          uses_symbol: "uses symbol",
                          inferred_api: "calls API",
                          html_loads_script: "loads script",
                          html_loads_style: "loads style",
                          service_reads_data: "reads data",
                          service_reads_config: "reads config",
                          route_reads_data: "reads data",
                          route_reads_config: "reads config",
                          service_returns_to_route: "returns data",
                          route_responds_to_frontend: "responds",
                          calls: "calls",
                          depends_on: "depends on",
                          impacts: "impacts",
                          import: "imports",
                          from_import: "imports",
                        };
                        const edgeLabel = _EDGE_LABELS[edge.type] || edge.type;
                        const isSemanticEdge = ["route_to_service", "service_to_model", "uses_symbol", "inferred_api", "html_loads_script", "html_loads_style", "service_reads_data", "service_reads_config", "route_reads_data", "route_reads_config"].includes(edge.type);
                        const isResponseEdge = ["service_returns_to_route", "route_responds_to_frontend"].includes(edge.type);
                        return (
                          <g key={i}>
                            <line
                              x1={x1} y1={y1} x2={x2} y2={y2}
                              stroke={isResponseEdge ? "#06b6d4" : isSemanticEdge ? "#8b5cf6" : "#6366f1"}
                              strokeWidth={isSemanticEdge || isResponseEdge ? 2 : 1.5}
                              strokeOpacity={isResponseEdge ? 0.6 : isSemanticEdge ? 0.7 : 0.5}
                              strokeDasharray={isResponseEdge ? "5 3" : undefined}
                              markerEnd="url(#flow-arrow)"
                            />
                            <text
                              x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 8}
                              textAnchor="middle" fontSize={8}
                              fill={isSemanticEdge ? "rgba(139,92,246,0.7)" : "rgba(148,163,184,0.5)"}
                              style={{ pointerEvents: "none" }}
                            >
                              {edgeLabel}
                            </text>
                          </g>
                        );
                      })}

                      {/* Nodes */}
                      {layoutNodes_.map(node => {
                        const color = node.changed ? "#ef4444"
                          : node.impacted ? "#f97316"
                          : (NODE_TYPE_COLORS[node.type] || "#6366f1");
                        const isSel = selectedNode?.id === node.id;
                        const NW = 110, NH = 52;

                        return (
                          <g
                            key={node.id}
                            className="flow-node"
                            transform={`translate(${node.x - NW / 2},${node.y - NH / 2})`}
                            style={{ cursor: "pointer" }}
                            onClick={e => { e.stopPropagation(); setSelectedNode(isSel ? null : node); }}
                          >
                            {/* Selected highlight */}
                            {isSel && (
                              <rect x={-3} y={-3} width={NW + 6} height={NH + 6} rx={8}
                                fill="none" stroke={color} strokeWidth={1} strokeOpacity={0.3} />
                            )}
                            {/* Body */}
                            <rect width={NW} height={NH} rx={6}
                              fill={isSel ? color + "20" : "rgba(15,23,42,0.8)"}
                              stroke={isSel ? color : color + "33"}
                              strokeWidth={isSel ? 2 : 1}
                            />
                            {/* Top accent bar */}
                            <rect width={NW} height={3} rx={6} fill={color} fillOpacity={0.7} />
                            {/* Type badge */}
                            <text x={NW / 2} y={18} textAnchor="middle" fontSize={7}
                              fill={color} fontWeight="bold"
                              style={{ pointerEvents: "none", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                              {NODE_TYPE_LABELS[node.type] || node.type}
                            </text>
                            {/* Label */}
                            <text x={NW / 2} y={33} textAnchor="middle" fontSize={9}
                              fill={isSel ? "white" : "rgba(255,255,255,0.85)"} fontWeight="600"
                              style={{ pointerEvents: "none" }}>
                              {node.label.length > 14 ? node.label.slice(0, 12) + "…" : node.label}
                            </text>
                            {/* Symbol */}
                            {node.symbol && (
                              <text x={NW / 2} y={45} textAnchor="middle" fontSize={7}
                                fill="rgba(148,163,184,0.5)"
                                style={{ pointerEvents: "none" }}>
                                {node.symbol.length > 16 ? node.symbol.slice(0, 14) + "…" : node.symbol}
                              </text>
                            )}
                            {/* Changed/impacted indicator */}
                            {(node.changed || node.impacted) && (
                              <rect x={-2} y={-2} width={NW + 4} height={NH + 4} rx={8}
                                fill="none"
                                stroke={node.changed ? "#ef4444" : "#f97316"}
                                strokeWidth={1.5} strokeOpacity={0.6}
                                strokeDasharray="3 2"
                              />
                            )}
                          </g>
                        );
                      })}
                    </g>
                  </svg>

                  {/* Legend */}
                  <div className="absolute bottom-3 left-3 flex flex-wrap gap-3">
                    {Array.from(new Set(currentPath.nodes.map(n => n.type))).slice(0, 5).map(type => (
                      <div key={type} className="flex items-center gap-1.5 text-[10px] text-slate-500">
                        <div className="h-2 w-2 rounded-sm" style={{ backgroundColor: NODE_TYPE_COLORS[type] || "#6366f1" }} />
                        {NODE_TYPE_LABELS[type] || type}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Side panel */}
              <div className="w-60 shrink-0">
                {selectedNode ? (
                  <NodeDetailPanel
                    node={selectedNode}
                    repoId={repoId}
                    onClose={() => setSelectedNode(null)}
                  />
                ) : (
                  <PathSummaryPanel path={currentPath} repoId={repoId} />
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Initial empty state */}
      {!flowData && !loading && !error && (
        <div className="rounded-xl border border-white/5 bg-slate-900/30 p-12 text-center">
          <Workflow className="h-10 w-10 text-slate-600 mx-auto mb-4" />
          <h3 className="text-sm font-semibold text-white mb-2">Execution Flow Map</h3>
          <p className="text-xs text-slate-400 max-w-sm mx-auto leading-relaxed mb-6">
            {mode === "primary"
              ? "Detecting application entrypoint…"
              : "Enter a route path, file path, function name, or changed files above to infer the likely execution flow through the repository."}
          </p>
          {mode !== "primary" && (
            <div className="flex flex-wrap justify-center gap-2 text-[11px] text-slate-600">
              <span className="rounded-lg border border-white/5 px-2 py-1">Route: /login</span>
              <span className="rounded-lg border border-white/5 px-2 py-1">File: app/services/auth.py</span>
              <span className="rounded-lg border border-white/5 px-2 py-1">Function: authenticate_user</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-panels
// ---------------------------------------------------------------------------

function NodeDetailPanel({ node, repoId, onClose }: { node: LayoutNode; repoId: string; onClose: () => void }) {
  const color = node.changed ? "#ef4444" : node.impacted ? "#f97316" : (NODE_TYPE_COLORS[node.type] || "#6366f1");

  return (
    <div className="rounded-lg border border-border/40 bg-slate-900/60 overflow-hidden shadow-premium">
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-white/5 bg-white/[0.02]">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-2 w-2 rounded-sm shrink-0" style={{ backgroundColor: color }} />
          <span className="text-[11px] font-bold text-slate-200 truncate">{node.label}</span>
        </div>
        <button onClick={onClose} className="text-slate-600 hover:text-slate-400 ml-2 shrink-0 transition-colors">
          <X size={14} />
        </button>
      </div>
      <div className="p-3.5 space-y-3.5">
        <div>
          <div className="text-[9px] font-bold uppercase tracking-wider text-slate-600 mb-1">Path</div>
          <div className="text-[11px] text-slate-400 font-mono break-all leading-relaxed opacity-80">{node.path}</div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-[9px] font-bold uppercase tracking-wider text-slate-600 mb-1">Type</div>
            <div className="text-[11px] font-bold" style={{ color }}>{NODE_TYPE_LABELS[node.type] || node.type}</div>
          </div>
          {node.symbol && (
            <div>
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-600 mb-1">Symbol</div>
              <div className="text-[11px] text-slate-300 font-mono">{node.symbol}</div>
            </div>
          )}
          {node.language && (
            <div>
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-600 mb-1">Language</div>
              <div className="text-[11px] text-slate-300">{node.language}</div>
            </div>
          )}
          {node.line_count > 0 && (
            <div>
              <div className="text-[9px] font-bold uppercase tracking-wider text-slate-600 mb-1">Lines</div>
              <div className="text-[11px] text-slate-300 font-medium">{node.line_count}</div>
            </div>
          )}
        </div>
        {(node.changed || node.impacted) && (
          <div className={cn(
            "text-xs px-2 py-1 rounded-lg border",
            node.changed ? "text-rose-400 bg-rose-500/10 border-rose-500/20" : "text-orange-400 bg-orange-500/10 border-orange-500/20"
          )}>
            {node.changed ? "Directly changed" : "Impacted by change"}
          </div>
        )}
        <div className="flex flex-col gap-1.5 pt-2 border-t border-white/5">
          {node.file_id ? (
            <Link href={`/repos/${repoId}/files/${node.file_id}`}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7">
                <FileCode className="mr-2 h-3.5 w-3.5" /> Open File
              </Button>
            </Link>
          ) : (
            <Link href={`/repos/${repoId}/files`}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7 text-slate-500">
                <FileCode className="mr-2 h-3.5 w-3.5" /> File Explorer
              </Button>
            </Link>
          )}
          <Link href={`/repos/${repoId}/flows?mode=file&query=${encodeURIComponent(node.path)}`}>
            <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7 text-indigo-400 hover:text-indigo-300">
              <Workflow className="mr-2 h-3.5 w-3.5" /> Trace Flow From Here
            </Button>
          </Link>
          <Link href={`/repos/${repoId}/graph?view=files`}>
            <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7">
              <GitBranch className="mr-2 h-3.5 w-3.5" /> Knowledge Graph
            </Button>
          </Link>
          <Link href={`/repos/${repoId}/chat`}>
            <Button variant="ghost" size="sm" className="w-full justify-start text-xs h-7">
              <ChevronRight className="mr-2 h-3.5 w-3.5" /> Ask Repo
            </Button>
          </Link>
        </div>
      </div>
    </div>
  );
}

function PathSummaryPanel({ path, repoId }: { path: FlowPath; repoId: string }) {
  // Compute flow confidence from edge types
  const _SEMANTIC_EDGE_TYPES = new Set(["route_to_service", "service_to_model", "uses_symbol", "inferred_api", "html_loads_script", "html_loads_style", "service_reads_data", "service_reads_config", "route_reads_data", "route_reads_config"]);
  const _EXACT_EDGE_TYPES = new Set(["route_to_service", "service_to_model", "uses_symbol"]);
  const _RESPONSE_EDGE_TYPES = new Set(["service_returns_to_route", "route_responds_to_frontend"]);
  const _DATA_EDGE_TYPES = new Set(["service_reads_data", "service_reads_config", "route_reads_data", "route_reads_config"]);

  const semanticEdges = path.edges.filter(e => _SEMANTIC_EDGE_TYPES.has(e.type)).length;
  const exactEdges = path.edges.filter(e => _EXACT_EDGE_TYPES.has(e.type)).length;
  const responseEdges = path.edges.filter(e => _RESPONSE_EDGE_TYPES.has(e.type)).length;
  const dataEdges = path.edges.filter(e => _DATA_EDGE_TYPES.has(e.type)).length;
  const totalEdges = path.edges.length;
  const flowConfidence = totalEdges === 0 ? "low"
    : exactEdges >= totalEdges * 0.5 ? "high"
    : semanticEdges >= totalEdges * 0.3 ? "medium"
    : "low";

  // Classify nodes into request vs response path
  const requestNodeTypes = new Set(["frontend_view", "frontend_component", "frontend_api_client", "entrypoint", "route_handler", "middleware"]);
  const processingNodeTypes = new Set(["service", "repository", "model"]);
  const dataNodeTypes = new Set(["config", "integration", "external_client"]);

  const requestNodes = path.nodes.filter(n => requestNodeTypes.has(n.type));
  const processingNodes = path.nodes.filter(n => processingNodeTypes.has(n.type));
  const dataNodes = path.nodes.filter(n => dataNodeTypes.has(n.type));
  const hasResponsePath = responseEdges > 0;

  return (
    <div className="rounded-lg border border-border/40 bg-slate-900/40 p-4 space-y-3 shadow-premium">
      <div>
        <div className="text-[11px] font-bold text-slate-200 uppercase tracking-wider mb-1.5">Path Summary</div>
        <p className="text-[11px] text-slate-500 leading-relaxed italic">"{path.explanation}"</p>
      </div>

      {/* Runtime path breakdown */}
      <div className="space-y-1.5 border-t border-white/5 pt-2.5">
        {requestNodes.length > 0 && (
          <div className="flex items-start gap-2 text-[11px]">
            <span className="text-slate-600 shrink-0 w-16">Request</span>
            <span className="text-slate-400 font-mono truncate">{requestNodes.map(n => n.label).join(" → ")}</span>
          </div>
        )}
        {processingNodes.length > 0 && (
          <div className="flex items-start gap-2 text-[11px]">
            <span className="text-slate-600 shrink-0 w-16">Processing</span>
            <span className="text-slate-400 font-mono truncate">{processingNodes.map(n => n.label).join(" → ")}</span>
          </div>
        )}
        {dataNodes.length > 0 && (
          <div className="flex items-start gap-2 text-[11px]">
            <span className="text-slate-600 shrink-0 w-16">Data</span>
            <span className="text-slate-400 font-mono truncate">{dataNodes.map(n => n.label).join(", ")}</span>
          </div>
        )}
        {dataEdges > 0 && (
          <div className="flex items-start gap-2 text-[11px]">
            <span className="text-slate-600 shrink-0 w-16">Config</span>
            <span className="text-slate-500">{dataEdges} data/config access{dataEdges !== 1 ? "es" : ""}</span>
          </div>
        )}
        <div className="flex items-start gap-2 text-[11px]">
          <span className="text-slate-600 shrink-0 w-16">Response</span>
          <span className={hasResponsePath ? "text-cyan-400" : "text-slate-700"}>
            {hasResponsePath ? `${responseEdges} return edge${responseEdges !== 1 ? "s" : ""} detected` : "No explicit response path inferred"}
          </span>
        </div>
      </div>

      {/* Stats */}
      <div className="space-y-1 border-t border-white/5 pt-2.5">
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Nodes</span>
          <span className="text-slate-300">{path.nodes.length}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Score</span>
          <span className="text-slate-300">{Math.round(path.score * 100)}%</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Confidence</span>
          <span className={flowConfidence === "high" ? "text-emerald-400" : flowConfidence === "medium" ? "text-amber-400" : "text-slate-500"}>
            {flowConfidence === "high" ? "High" : flowConfidence === "medium" ? "Medium" : "Low"}
            {exactEdges > 0 && ` · ${exactEdges} exact`}
          </span>
        </div>
      </div>

      <div className="pt-1 border-t border-white/5 text-[11px] text-slate-600 space-y-0.5">
        <div>Click a node to inspect it</div>
        <div>Scroll to zoom · Drag to pan</div>
      </div>
    </div>
  );
}
