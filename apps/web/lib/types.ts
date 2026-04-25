export type Repository = {
  id: string;
  repo_url: string;
  default_branch: string;
  status: string;
  primary_language?: string | null;
  framework?: string | null;
  languages_used?: string[];
  created_at?: string;
};

export type FileRecord = {
  id: string;
  path: string;
  language?: string | null;
  file_kind: string;
  line_count?: number | null;
  parse_status?: string;
};

export type FileListResponse = {
  repository_id?: string;
  status?: string | null;
  total: number;
  items: FileRecord[];
};

export type FileDetailResponse = {
  id: string;
  repository_id: string;
  path: string;
  language?: string | null;
  file_kind: string;
  line_count?: number | null;
  parse_status?: string | null;
  is_generated?: boolean;
  is_vendor?: boolean;
  content?: string | null;
  raw_url?: string | null;
  is_binary?: boolean;
};

export type SearchResultItem = {
  chunk_id: string;
  file_id?: string | null;
  file_path?: string | null;
  score: number;
  chunk_type: string;
  start_line?: number | null;
  end_line?: number | null;
  matched_lines?: number[];
  snippet: string;
  match_type?: string | null;
};


export type SemanticSearchResponse = {
  repository_id: string;
  query: string;
  total: number;
  items: SearchResultItem[];
};

export type RenameAnalysis = {
  symbol_name: string;
  new_name: string;
  declaration_line: number | string;
  same_file_references: Array<{ line_no: number; line_text: string }>;
  declaration_only_rename_breaks: boolean;
  full_rename_safe: boolean;
  language: string;
  error_if_partial: string;
};

export type AskRepoResponse = {
  question: string;
  answer: string;
  citations: Array<{
    file_id?: string | null;
    file_path?: string | null;
    start_line?: number | null;
    end_line?: number | null;
    matched_lines?: number[];
    chunk_id: string;
    match_type?: string | null;
  }>;

  mode: string;
  llm_model?: string | null;
  confidence?: string | null;
  query_type?: string | null;
  resolved_file?: string | null;
  resolved_line_number?: number | null;
  matched_line?: string | null;
  enclosing_scope?: string | null;
  line_type?: string | null;
  rename_analysis?: RenameAnalysis | null;
  answer_mode?: string | null;
  notes?: string[] | null;
  snippet_found?: boolean | null;
  // New: answer confidence and evidence breakdown
  answer_confidence?: "high" | "medium" | "low" | null;
  evidence_breakdown?: {
    exact_edges_used: number;
    inferred_edges_used: number;
    symbol_hits_used: number;
    semantic_hits_used: number;
    total_chunks: number;
  } | null;
  // New: structured answer for analyst console UI
  structured_answer?: {
    summary?: string;
    sections?: Array<{
      key: string;
      title: string;
      kind: "summary" | "stack" | "architecture" | "capabilities" | "flow" | "files" | "risks" | "notes" | "symbol" | "usage" | "impact" | "evidence";
      content: string;
      priority: number;
      collapsible?: boolean;
      default_open?: boolean;
    }>;
    key_files?: Array<{
      path: string;
      reason?: string;
      role?: string | null;
    }>;
    evidence_preview?: Array<{
      file_path: string;
      line_start?: number | null;
      line_end?: number | null;
      label?: string;
      snippet?: string;
      match_type?: string | null;
    }>;
    answer_mode?: "high_level" | "flow" | "symbol" | "impact" | "code" | "fallback";
  } | null;
};

export type HotspotItem = {
  file_id: string;
  path: string;
  language?: string | null;
  file_kind: string;
  risk_score: number;
  complexity_score: number;
  dependency_score: number;
  change_proneness_score: number;
  test_proximity_score: number;
  symbol_count: number;
  inbound_dependencies: number;
  outbound_dependencies: number;
  risk_level: string;
};

export type HotspotListResponse = {
  repository_id: string;
  total: number;
  items: HotspotItem[];
};

export type OnboardingDocumentResponse = {
  id: string;
  repository_id: string;
  version: number;
  title: string;
  content_markdown: string;
  generation_mode: string;
  llm_model?: string | null;
  created_at: string;
};

export type PRImpactResponse = {
  repository_id: string;
  changed_files: string[];
  changed_symbols: string[];
  impacted_count: number;
  risk_level: string;
  total_impact_score: number;
  summary: string;
  mode: string;
  impacted_files: Array<{
    file_id: string;
    path: string;
    language?: string | null;
    depth: number;
    inbound_dependencies: number;
    outbound_dependencies: number;
    risk_score: number;
    impact_score: number;
    impact_level: string;
    reasons: string[];
    edge_types: string[];
    is_directly_changed: boolean;
    categories: string[];
    primary_category: string;
    symbol_hits: string[];
    why_now: string;
    reason_tag?: string;
    evidence_strength?: string;
  }>;
  reviewer_suggestions: Array<{
    reviewer_hint: string;
    reason: string;
    why_now: string;
  }>;
  flow_paths: Array<{
    summary: string;
    score: number;
    nodes: Array<{ path: string; type: string; label: string }>;
  }>;
  notes: string[];
  // New enriched sections
  input_extraction?: {
    changed_files: string[];
    changed_symbols: string[];
    added_lines: number;
    removed_lines: number;
    analysis_source: string;
  };
  blast_radius?: {
    direct_dependents_count: number;
    upstream_dependencies_count: number;
    total_blast_radius_count: number;
    impacted_modules: string[];
  };
  risk_assessment?: {
    overall_risk_level: string;
    overall_risk_score: number;
    risk_reasons: string[];
  };
  affected_flows?: Array<{
    flow_name: string;
    confidence: number;
    summary: string;
    path_nodes: string[];
    why_relevant: string;
  }>;
  review_priorities?: Array<{
    file_id?: string | null;
    path: string;
    reason: string;
    priority_score: number;
    primary_category: string;
  }>;
  possible_regressions?: Array<{
    description: string;
    affected_area: string;
    confidence: string;
  }>;
  evidence?: Array<{
    signal: string;
    file_path: string;
    detail: string;
  }>;
  executive_summary?: string;
  partial_failure?: boolean;
  partial_failure_reasons?: string[];
  impact_confidence?: string;
  evidence_breakdown?: {
    exact_edges_used: number;
    inferred_edges_used: number;
    flow_links_used: number;
    symbol_links_used: number;
    semantic_only_hits: number;
    total_impacted: number;
  };
  // New: change classification and score explanation
  change_types?: string[];
  is_trivial_change?: boolean;
  score_explanation?: string;
};

export type RefreshJob = {
  id: string;
  repository_id: string;
  job_type: string;
  trigger_source: string;
  event_type: string;
  branch?: string | null;
  status: string;
  changed_files: string[];
  summary?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type RefreshJobListResponse = {
  repository_id: string;
  total: number;
  items: RefreshJob[];
};

// ---------------------------------------------------------------------------
// Graph types
// ---------------------------------------------------------------------------

export type GraphNode = {
  id: string;
  path: string;
  name: string;
  folder: string;
  language: string | null;
  file_kind: string;
  line_count: number;
  is_generated: boolean;
  is_vendor: boolean;
  is_test: boolean;
  degree: number;
  // layout — assigned client-side
  x?: number;
  y?: number;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  edge_type: "import" | "from_import" | "call" | "require" | "export" | string;
  count: number;
};

export type RepoGraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_files: number;
  total_resolved_edges: number;
  edge_type_counts: Record<string, number>;
  truncated: boolean;
};

// ---------------------------------------------------------------------------
// Knowledge Graph (multi-mode)
// ---------------------------------------------------------------------------

export type KnowledgeGraphNode = {
  id: string;
  type: "cluster" | "file";
  label: string;
  path: string;
  name?: string;
  folder?: string;
  cluster_id: string | null;
  risk_score: number;
  size: number;
  degree: number;
  language: string | null;
  file_kind: string;
  line_count?: number;
  is_generated?: boolean;
  is_vendor?: boolean;
  is_test?: boolean;
  meta: {
    file_count: number;
    changed: boolean;
    impacted: boolean;
  };
};

export type KnowledgeGraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  edge_type: string;
  weight: number;
  count: number;
  meta: {
    is_inferred?: boolean;
    resolved_count?: number;
    inferred_count?: number;
    all_types?: string[];
    [key: string]: unknown;
  };
};

export type KnowledgeGraphData = {
  view: "clusters" | "files" | "hotspots" | "impact";
  repo_id: string;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  legend: Record<string, string>;
  edge_type_counts?: Record<string, number>;
  total_files: number;
  total_resolved_edges: number;
  total_inferred_edges?: number;
  truncated: boolean;
  graph_stats?: {
    node_count: number;
    edge_count: number;
    resolved_edge_count: number;
    inferred_edge_count: number;
    isolated_node_count?: number;
    disconnected_clusters?: number;
    density: number;
    sparse: boolean;
  };
};

// ---------------------------------------------------------------------------
// Execution Flow Map types
// ---------------------------------------------------------------------------

export type FlowNode = {
  id: string;
  file_id: string | null;   // stable file identifier for deep-linking
  label: string;
  type: string;       // route_handler | service | repository | model | utility | middleware | worker | external_client | module
  path: string;
  symbol: string | null;
  role: string;
  language: string | null;
  line_count: number;
  changed: boolean;
  impacted: boolean;
};

export type FlowEdge = {
  source: string;
  target: string;
  type: string;       // calls | depends_on | impacts
};

export type FlowPath = {
  id: string;
  score: number;
  explanation: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
};

export type FlowSummary = {
  entrypoint: string;
  estimated_confidence: number;
  path_count: number;
  notes: string[];
};

export type FlowData = {
  mode: "route" | "file" | "function" | "impact" | "primary";
  query: string;
  repo_id: string;
  summary: FlowSummary;
  paths: FlowPath[];
  // primary mode extras
  entrypoint_candidates?: Array<{
    path: string;
    name: string;
    confidence: number;
    role: string;
    language: string | null;
  }>;
  selected_entrypoint?: string;
};
