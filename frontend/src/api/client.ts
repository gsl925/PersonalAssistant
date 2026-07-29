import type {
  Agent,
  AgentToggleResponse,
  CapabilityTiers,
  CapabilityTiersResponse,
  Document,
  DocumentContent,
  DocumentFilters,
  DocumentListResponse,
  MindmapResponse,
  OcrEngineResponse,
  OllamaModelsResponse,
  Project,
  ActionItemListResponse,
  RetryResponse,
  SearchResponse,
  TestModelResponse,
  DigestStatusResponse,
  Todo,
  TodoListResponse,
} from "./types";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore, keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function buildQuery<T extends object>(params: T): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  listDocuments(filters: DocumentFilters = {}): Promise<DocumentListResponse> {
    return request(`/api/knowledge/documents${buildQuery(filters)}`);
  },

  listTimeline(filters: DocumentFilters = {}): Promise<DocumentListResponse> {
    return request(`/api/knowledge/timeline${buildQuery(filters)}`);
  },

  getDocument(docId: string): Promise<Document> {
    return request(`/api/knowledge/documents/${docId}`);
  },

  getDocumentContent(docId: string): Promise<DocumentContent> {
    return request(`/api/knowledge/documents/${docId}/content`);
  },

  retryDocument(docId: string): Promise<RetryResponse> {
    return request(`/api/knowledge/documents/${docId}/retry`, { method: "POST" });
  },

  listProjects(): Promise<Project[]> {
    return request(`/api/knowledge/projects`);
  },

  listProjectDocuments(
    projectId: string,
    filters: { skip?: number; limit?: number } = {}
  ): Promise<DocumentListResponse> {
    return request(`/api/knowledge/projects/${projectId}/documents${buildQuery(filters)}`);
  },

  search(q: string, limit = 10): Promise<SearchResponse> {
    return request(`/api/knowledge/search${buildQuery({ q, limit })}`);
  },

  getMindmap(docId: string): Promise<MindmapResponse> {
    return request(`/api/knowledge/mindmap/${docId}`);
  },

  listActionItems(dueBefore?: string): Promise<ActionItemListResponse> {
    return request(`/api/knowledge/action-items${buildQuery({ due_before: dueBefore })}`);
  },

  getCapabilityTiers(): Promise<CapabilityTiersResponse> {
    return request(`/api/settings/capability-tiers`);
  },

  updateCapabilityTiers(tiers: CapabilityTiers): Promise<CapabilityTiersResponse> {
    return request(`/api/settings/capability-tiers`, {
      method: "PATCH",
      body: JSON.stringify({ tiers }),
    });
  },

  getOllamaModels(): Promise<OllamaModelsResponse> {
    return request(`/api/settings/ollama-models`);
  },

  testModel(provider: string, model: string): Promise<TestModelResponse> {
    return request(`/api/settings/test-model`, {
      method: "POST",
      body: JSON.stringify({ provider, model }),
    });
  },

  triggerDigest(): Promise<{ status: string; message: string }> {
    return request(`/api/settings/trigger-digest`, { method: "POST" });
  },

  getDigestStatus(): Promise<DigestStatusResponse> {
    return request(`/api/settings/digest-status`);
  },

  getOcrEngine(): Promise<OcrEngineResponse> {
    return request(`/api/settings/ocr-engine`);
  },

  updateOcrEngine(engine: string): Promise<OcrEngineResponse> {
    return request(`/api/settings/ocr-engine`, {
      method: "PATCH",
      body: JSON.stringify({ engine }),
    });
  },

  listAgents(): Promise<Agent[]> {
    return request(`/api/agents/`);
  },

  toggleAgent(name: string): Promise<AgentToggleResponse> {
    return request(`/api/agents/${name}/toggle`, { method: "PATCH" });
  },

  createTodo(text: string, source = "dashboard"): Promise<Todo> {
    return request(`/api/todos`, {
      method: "POST",
      body: JSON.stringify({ text, source }),
    });
  },

  listTodos(params: { status?: string; due_before?: string } = {}): Promise<TodoListResponse> {
    return request(`/api/todos${buildQuery(params)}`);
  },

  updateTodoStatus(todoId: string, status: string): Promise<{ status: string; todo_id: string }> {
    return request(`/api/todos/${todoId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  },

  snoozeTodo(todoId: string): Promise<{ status: string; todo_id: string; remind_at: string }> {
    return request(`/api/todos/${todoId}/snooze`, { method: "POST" });
  },
};

export { ApiError };
