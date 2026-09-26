"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Background, Controls, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

type Project = { id: string; name: string; files: number };
type Briefing = {
  id: string;
  question: string;
  headline: string;
  what: string[];
  why: string[];
  gaps: string[];
  evidence: { source: string; relationship: string; target: string }[];
  steps?: { id: string; label: string; detail: string }[];
  path?: { kind: string; name: string }[];
  citations?: { kind: string; name: string; path: string; line?: number | null }[];
};
type Graph = { nodes: { id: string; labels: string[]; name: string }[]; edges: { source: string; target: string; type: string }[] };

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : response.statusText || "Request failed");
  return body as T;
}

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [question, setQuestion] = useState("");
  const [github, setGithub] = useState("");
  const [graph, setGraph] = useState<Graph | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const project = projects.find((item) => item.id === projectId) ?? null;
  const showContext = Boolean(briefing && (briefing.evidence.length || briefing.steps?.length || briefing.path?.length));

  const load = useCallback(async (id?: string) => {
    const listed = await json<{ projects: Project[] }>("/api/projects");
    setProjects(listed.projects);
    const next = id ?? listed.projects[0]?.id;
    if (!next) {
      setProjectId(null);
      setBriefing(null);
      setGraph(null);
      return;
    }
    setProjectId(next);
    const detail = await json<{ briefings: Briefing[] }>(`/api/projects/${next}`);
    setBriefing(detail.briefings[0] ?? null);
    setGraph(await json<Graph>(`/api/projects/${next}/graph`));
  }, []);

  useEffect(() => {
    load().catch((err: Error) => setError(err.message));
  }, [load]);

  const flow = useMemo(() => {
    const nodes = (graph?.nodes ?? []).slice(0, 40).map((node, index) => ({
      id: node.id,
      position: { x: (index % 8) * 160, y: Math.floor(index / 8) * 90 },
      data: { label: `${node.labels[0] ?? "Node"}\n${node.name}` },
      style: { background: "#181c25", color: "#eceef3", border: "1px solid #262b36", fontSize: 11, whiteSpace: "pre-wrap" as const, width: 140 },
    }));
    const edges = (graph?.edges ?? []).slice(0, 80).map((edge, index) => ({
      id: `${edge.source}-${edge.type}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      label: edge.type,
    }));
    return { nodes, edges };
  }, [graph]);

  async function ingestGithub(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const report = await json<{ repositoryId: string }>("/api/ingest/github", { method: "POST", body: JSON.stringify({ url: github }) });
      setNotice("Repository indexed.");
      await load(report.repositoryId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "GitHub ingest failed");
    } finally {
      setBusy(false);
    }
  }

  async function loadDemo() {
    setBusy(true);
    setError(null);
    try {
      const report = await json<{ repositoryId: string }>("/api/demo/billing", { method: "POST" });
      setNotice("Sample indexed.");
      await load(report.repositoryId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Demo ingest failed");
    } finally {
      setBusy(false);
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!projectId || !question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const answer = await json<Briefing>(`/api/projects/${projectId}/ask`, {
        method: "POST",
        body: JSON.stringify({ question: question.trim() }),
      });
      setBriefing(answer);
      setGraph(await json<Graph>(`/api/projects/${projectId}/graph`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask failed");
    } finally {
      setBusy(false);
    }
  }

  async function openFile(path: string) {
    if (!projectId) return;
    const file = await json<{ content: string }>(`/api/projects/${projectId}/files?path=${encodeURIComponent(path)}`);
    setCode(file.content);
  }

  return (
    <div className={`app${showContext ? " with-ctx" : ""}`}>
      <header className="top">
        <div className="brand">
          <span className="logo" />
          DevMind
        </div>
        <span className="muted">{project ? project.name : "Connect a repository"}</span>
      </header>
      {(error || notice) && (
        <div className={`banner ${error ? "bad" : ""}`}>
          {error || notice}
          <button type="button" onClick={() => { setError(null); setNotice(null); }}>Dismiss</button>
        </div>
      )}

      {!project ? (
        <div className="onboard">
          <div className="onboard-copy">
            <h1>Connect a repository</h1>
            <p>Index a GitHub repo or the billing sample. Answers come from the Neo4j graph.</p>
          </div>
          <div className="onboard-grid">
            <form className="card" onSubmit={ingestGithub}>
              <h2>GitHub</h2>
              <input value={github} onChange={(event) => setGithub(event.target.value)} placeholder="https://github.com/owner/repo" />
              <button className="primary" disabled={busy || github.length < 12}>Clone and index</button>
            </form>
            <div className="card">
              <h2>Sample</h2>
              <p className="muted">bundled billing-service with decisions and issues</p>
              <button type="button" disabled={busy} onClick={() => void loadDemo()}>Index billing-service</button>
            </div>
          </div>
        </div>
      ) : (
        <div className="shell">
          <aside className="rail">
            <p className="kicker">Repositories</p>
            {projects.map((item) => (
              <button key={item.id} className={item.id === projectId ? "repo on" : "repo"} onClick={() => void load(item.id)}>
                <b>{item.name}</b>
                <span>{item.files} files</span>
              </button>
            ))}
            <form onSubmit={ingestGithub}>
              <input value={github} onChange={(event) => setGithub(event.target.value)} placeholder="GitHub URL" />
              <button className="primary" disabled={busy || github.length < 12}>Clone</button>
            </form>
          </aside>
          <main className="stage">
            <form className="ask" onSubmit={ask}>
              <textarea value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} placeholder={`Ask about ${project.name}…`} />
              <button className="primary" disabled={busy || !question.trim()}>{busy ? "Walking graph…" : "Ask"}</button>
            </form>
            {briefing ? (
              <article className="answer">
                <p className="muted">{briefing.question}</p>
                <h2>{briefing.headline}</h2>
                <div className="split">
                  <section>
                    <h3>What</h3>
                    <ul>{briefing.what.map((line) => <li key={line}>{line}</li>)}</ul>
                  </section>
                  <section>
                    <h3>Why</h3>
                    <ul>{briefing.why.map((line) => <li key={line}>{line}</li>)}</ul>
                  </section>
                </div>
                {briefing.citations?.map((item) => (
                  <button key={`${item.path}-${item.name}`} className="cite" onClick={() => void openFile(item.path)}>
                    {item.path}
                  </button>
                ))}
              </article>
            ) : (
              <p className="muted">Ask what a function does, or why a decision was made.</p>
            )}
            {code && <pre><code>{code.slice(0, 4000)}</code></pre>}
            {graph && graph.nodes.length > 0 && (
              <div className="graph">
                <ReactFlow nodes={flow.nodes} edges={flow.edges} fitView>
                  <Background />
                  <Controls />
                </ReactFlow>
              </div>
            )}
          </main>
          {showContext && briefing && (
            <aside className="ctx">
              {briefing.path && briefing.path.length > 0 && (
                <>
                  <p className="kicker">Why path</p>
                  <p className="muted">{briefing.path.map((item) => `${item.kind}: ${item.name}`).join(" → ")}</p>
                </>
              )}
              {briefing.steps && briefing.steps.length > 0 && (
                <>
                  <p className="kicker">Agent</p>
                  <ol>
                    {briefing.steps.map((step) => (
                      <li key={step.id}>{step.label}: {step.detail}</li>
                    ))}
                  </ol>
                </>
              )}
              {briefing.evidence.length > 0 && (
                <>
                  <p className="kicker">Evidence</p>
                  <ol className="trail">
                    {briefing.evidence.map((item, index) => (
                      <li key={`${item.source}-${index}`}>
                        <span>{item.source}</span>
                        <em>{item.relationship}</em>
                        <span>{item.target}</span>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </aside>
          )}
        </div>
      )}
    </div>
  );
}
