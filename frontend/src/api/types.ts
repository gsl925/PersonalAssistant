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
  ai_insight: string | null;
  user_note: string | null;
  processing_status: ProcessingStatus | string;
  created_at: string;
  updated_at: string | null;
  tags: Tag[];
  projects: Project[];
}

export interface InsightPreview {
  status: string;
  preview_id: string | null;
  title: string | null;
  insight: string | null;
  source_url: string | null;
  is_video: boolean | null;
  message: string | null;
}

export interface SaveInsightResponse {
  status: string;
  doc_id: string | null;
  message: string | null;
  title: string | null;
  summary: string | null;
  category: string | null;
  tags: string[] | null;
  ai_insight: string | null;
}

export interface DocumentContent {
  id: string;
  title: string | null;
  original_content: string | null;
  corrected_content: string | null;
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

export interface TodoRecurrence {
  frequency: string; // daily / weekly / monthly
  weekday: number | null; // 0=Mon..6=Sun, only for weekly
  day_of_month: number | null; // 1-31, only for monthly
  time: string; // "HH:MM"
}

export interface Todo {
  id: string;
  content: string;
  status: string;
  start_date: string | null;
  due_date: string | null;
  source: string;
  source_url: string | null;
  recurrence?: TodoRecurrence | null;
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

// --- project_sync.py ---
// TrackedProject* naming is deliberate — don't call this "Project"/"Projects":
// that name is already taken above by the knowledge-base "Project" (a
// document-grouping entity, /api/knowledge/projects). This is a completely
// different concept (an entry from the backend's projects.yaml).

export interface PendingDiscussItem {
  number: number;
  content: string;
}

export interface TrackedProjectOut {
  name: string;
  label: string;
  pending_items: PendingDiscussItem[];
}

export interface TrackedProjectListResponse {
  items: TrackedProjectOut[];
}

export interface AddTrackedProjectResponse {
  status: string;
  name?: string;
  label?: string;
}

export interface BroadcastInstructionResponse {
  succeeded: string[];
  failed: string[];
}

// --- dev_tasks.py ---

export interface ToolOut {
  name: string;
  display_name: string;
  description: string | null;
}

export interface ToolListResponse {
  items: ToolOut[];
}

export interface AttachmentUploadResponse {
  relative_path: string;
}

export interface DevTaskSubmitRequest {
  description: string;
  reference_path?: string;
  attachment_path?: string;
  target_tool?: string;
  new_tool_name?: string;
  notify: "default" | "none";

  task_type?: string;
  example_input?: string;
  example_output?: string;

  input_source?: string[];
  file_filter?: string[];
  filter_detail?: string;
  folder_depth?: string;

  extraction_method?: string[];
  calc_method?: string[];
  exception_handling?: string[];
  comparison_scope?: string[];

  output_format?: string[];
  completion_report?: string[];
  result_format?: string;
  keep_full_log?: boolean;

  additional_notes?: string;
  local_model?: string;
}

export interface DevTaskSubmitResponse {
  ok: boolean;
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
