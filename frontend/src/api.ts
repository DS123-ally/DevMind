export type Inventory = {
  counts: Record<string, number>;
  relationships: Record<string, number>;
};

export type TreeNode = {
  name: string;
  path: string;
  type: "dir" | "file";
  language?: string;
  children: TreeNode[];
};

export type Evidence = {
  source: string;
  relationship: string;
  target: string;
  note?: string;
};

export type Briefing = {
  id: string;
  question: string;
  mode: "what" | "why" | "both";
  headline: string;
  what: string[];
  why: string[];
  gaps: string[];
  evidence: Evidence[];
  voice: string;
  createdAt: string;
};

export type ProjectDetail = {
  id: string;
  name: string;
  path: string;
  summary?: string;
  updatedAt?: string;
  technologies: { name: string; category: string }[];
  decisions: { id: string; title: string; status: string; date?: string }[];
  inventory: Inventory;
  briefings: Briefing[];
};

export type ProjectSummary = {
  id: string;
  name: string;
  path: string;
  summary?: string;
  files: number;
};

export type Health = {
  status: string;
  neo4j: string;
  llm: string;
  error?: string | null;
};

export type IngestReport = {
  repositoryId: string;
  name: string;
  files: number;
  symbols: number;
  decisions: number;
  technologies: string[];
  warnings: string[];
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Request failed";
    throw new Error(detail);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  projects: () => request<{ projects: ProjectSummary[] }>("/api/projects"),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  tree: (id: string) => request<TreeNode>(`/api/projects/${id}/tree`),
  ingest: (path: string, name?: string) =>
    request<IngestReport>("/api/ingest", { method: "POST", body: JSON.stringify({ path, name }) }),
  demoBilling: () => request<IngestReport>("/api/demo/billing", { method: "POST" }),
  demoSelf: () => request<IngestReport>("/api/demo/self", { method: "POST" }),
  ask: (id: string, question: string, mode: string) =>
    request<Briefing>(`/api/projects/${id}/ask`, {
      method: "POST",
      body: JSON.stringify({ question, mode: mode === "auto" ? null : mode }),
    }),
  decision: (id: string, payload: { title: string; rationale: string; decider?: string; aboutIds: string[] }) =>
    request<{ id: string; title: string }>(`/api/projects/${id}/decisions`, {
      method: "POST",
      body: JSON.stringify({ ...payload, status: "accepted" }),
    }),
};
