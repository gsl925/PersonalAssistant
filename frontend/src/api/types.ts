// Mirrors backend/api/knowledge.py, ingest.py, settings.py, agents.py Pydantic
// models exactly. Do NOT reference backend/api/schemas.py — it's an orphaned
// file unused by any router and defines an incompatible, stale shape.

export interface Tag {
  keyword: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
}

export type ProcessingStatus = "pending" | "processing" | "completed" | "failed";

export interface Document {
  id: string;
  source_type: string;
  title: string | null;
  summary: string | null;
  category: string | null;
  file_path: string | null;
  source_url: string | null;
  agent_used: string | null;
  processing_status: ProcessingStatus | string;
  created_at: string;
  updated_at: string | null;
  tags: Tag[];
  projects: Project[];
}

export interface DocumentContent {
  id: string;
  title: string | null;
  original_content: string | null;
  type_specific_data: Record<string, unknown> | null;
}

// `count` is the number of items on THIS page (== items.length, bounded by
// `limit`), not a total row count — there is no total anywhere in this API.
export interface DocumentListResponse {
  items: Document[];
  skip: number;
  limit: number;
  count: number;
}

export interface DocumentFilters {
  skip?: number;
  limit?: number;
  source_type?: string;
  category?: string;
  project_id?: string;
  start_date?: string;
  end_date?: string;
}

export interface SearchResult {
  id: string;
  score: number;
  payload: Record<string, unknown>;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export interface MindmapNode {
  id: string;
  title: string | null;
  source_type: string;
  category: string | null;
  tags: string[];
}

export interface MindmapEdge {
  source: string;
  target: string;
  relation_type: string;
  score: number;
}

export interface MindmapResponse {
  center_id: string;
  nodes: MindmapNode[];
  edges: MindmapEdge[];
}

export interface ActionItem {
  task: string;
  owner: string | null;
  due_date: string | null;
  source_doc_id: string;
  source_title: string | null;
  meeting_date: string | null;
  created_at: string;
}

export interface ActionItemListResponse {
  items: ActionItem[];
  count: number;
}

// --- todos.py ---
// Separate from ActionItem above: todos are quick-captured by the user
// (Telegram/desktop/dashboard) and have a real status (pending/done/cancelled),
// unlike meeting-derived action_items which have no "done" flag.

export interface TodoReminder {
  label: string; // start / midpoint / due
  remind_at: string;
}

export interface Todo {
  id: string;
  content: string;
  status: string;
  start_date: string | null;
  due_date: string | null;
  source: string;
  source_url: string | null;
  created_at: string;
  reminders?: TodoReminder[] | null;
}

export interface TodoListResponse {
  items: Todo[];
  count: number;
}

export interface RetryResponse {
  status: string;
  doc_id: string;
  message: string;
  title?: string | null;
  summary?: string | null;
  category?: string | null;
  tags?: string[] | null;
}

// --- settings.py ---

export interface ModelEntry {
  provider: string;
  model: string;
}

export type CapabilityTiers = Record<string, ModelEntry[]>;

export interface CapabilityTiersResponse {
  tiers: CapabilityTiers;
}

export interface OllamaModel {
  name: string;
  size: number | null;
  modified_at: string | null;
  digest: string | null;
}

export interface OllamaModelsResponse {
  models: OllamaModel[];
}

export interface DigestStatusResponse {
  last_sent_date: string | null;
  today: string;
  sent_today: boolean;
}

export interface OcrEngineResponse {
  engine: string;
}

export interface TestModelResponse {
  provider: string;
  model: string;
  reachable: boolean;
  detail: string;
}

// --- agents.py ---

export interface Agent {
  name: string;
  description: string;
  model: string;
  tools: string[];
  enabled: boolean;
  output_schema: string;
  version: string;
  skill_dir: string;
}

export interface AgentToggleResponse {
  name: string;
  enabled: boolean;
  message: string;
}

// --- ingest.py ---

export interface IngestResponse {
  status: string;
  doc_id: string | null;
  message: string;
  agent_name: string | null;
  confidence: number | null;
  available_agents: string[] | null;
}
