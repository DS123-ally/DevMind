import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type Briefing, type Health, type ProjectDetail, type ProjectSummary, type TreeNode } from "./api";

type Mode = "auto" | "what" | "why";
type View = "brief" | "files" | "memory";

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [view, setView] = useState<View>("brief");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [github, setGithub] = useState("");
  const [decisionTitle, setDecisionTitle] = useState("");
  const [decisionRationale, setDecisionRationale] = useState("");
  const [decider, setDecider] = useState("");
  const [connectOpen, setConnectOpen] = useState(false);

  const selected = useMemo(
    () => project?.briefings.find((item) => item.id === selectedId) ?? project?.briefings[0] ?? null,
    [project, selectedId],
  );
  const showContext = Boolean(
    view === "brief" && selected && (selected.path?.length || selected.evidence?.length || selected.steps?.length),
  );

  async function refreshProjects(selectId?: string) {
    const listed = await api.projects();
    setProjects(listed.projects);
    const next = selectId ?? listed.projects[0]?.id;
    if (next) {
      const detail = await api.project(next);
      setProject(detail);
      setSelectedId(detail.briefings[0]?.id ?? null);
      try {
        setTree(await api.tree(next));
      } catch {
        setTree(null);
      }
    } else {
      setProject(null);
      setTree(null);
    }
  }

  useEffect(() => {
    api
      .health()
      .then(async (status) => {
        setHealth(status);
        if (status.neo4j === "connected") await refreshProjects();
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  async function runIngest(action: () => Promise<{ repositoryId: string; files: number; symbols: number; decisions: number; name: string }>) {
    setBusy(true);
    setError(null);
    try {
      const report = await action();
      setNotice(`${report.name} indexed · ${report.files} files · ${report.symbols} symbols · ${report.decisions} decisions`);
      setConnectOpen(false);
      await refreshProjects(report.repositoryId);
      setHealth(await api.health());
      setView("brief");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setBusy(false);
    }
  }

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    if (!project || !question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const briefing = await api.ask(project.id, question.trim(), mode);
      const detail = await api.project(project.id);
      setProject(detail);
      setSelectedId(briefing.id);
      setView("brief");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The graph could not answer");
    } finally {
      setBusy(false);
    }
  }

  async function onDecision(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      await api.decision(project.id, {
        title: decisionTitle,
        rationale: decisionRationale,
        decider: decider || undefined,
        aboutIds: [],
      });
      setDecisionTitle("");
      setDecisionRationale("");
      setNotice("Decision written to Neo4j.");
      setProject(await api.project(project.id));
      setView("memory");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not store the decision");
    } finally {
      setBusy(false);
    }
  }

  const counts = project?.inventory.counts ?? {};
  const neoOk = health?.neo4j === "connected";

  return (
    <div className={`app${showContext ? " with-ctx" : ""}`}>
      <header className="top">
        <div className="brand">
          <span className="logo" aria-hidden="true" />
          <span>DevMind</span>
        </div>
        {project && (
          <div className="tabs" role="tablist">
            {([
              ["brief", "Briefing"],
              ["files", "Files"],
              ["memory", "Memory"],
            ] as const).map(([id, label]) => (
              <button key={id} className={view === id ? "on" : ""} onClick={() => setView(id)} type="button">
                {label}
              </button>
            ))}
          </div>
        )}
        <div className="pills">
          <span className={neoOk ? "pill ok" : "pill bad"}>{neoOk ? "Neo4j connected" : `Neo4j ${health?.neo4j ?? "…"}`}</span>
          {health?.llm && health.llm !== "off" && <span className="pill">LLM {health.llm}</span>}
        </div>
      </header>

      {(error || notice) && (
        <div className={`banner ${error ? "bad" : ""}`}>
          <span>{error || notice}</span>
          <button type="button" onClick={() => { setError(null); setNotice(null); }}>
            Dismiss
          </button>
        </div>
      )}

      {!project ? (
        <EmptyState
          busy={busy}
          github={github}
          path={path}
          onGithub={setGithub}
          onPath={setPath}
          onGithubSubmit={() => runIngest(() => api.github(github))}
          onPathSubmit={() => runIngest(() => api.ingest(path))}
          onDemo={() => runIngest(api.demoBilling)}
        />
      ) : (
        <div className="layout">
          <aside className="rail">
            <div className="rail-head">
              <span>Repositories</span>
              <button type="button" className="text-btn" onClick={() => setConnectOpen((open) => !open)}>
                {connectOpen ? "Cancel" : "Add"}
              </button>
            </div>
            <div className="repos">
              {projects.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={item.id === project.id ? "repo on" : "repo"}
                  onClick={() => refreshProjects(item.id).catch((err: Error) => setError(err.message))}
                >
                  <b>{item.name}</b>
                  <span>{item.files} files</span>
                </button>
              ))}
            </div>
            {connectOpen && (
              <div className="connect">
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void runIngest(() => api.github(github));
                  }}
                >
                  <input
                    value={github}
                    onChange={(event) => setGithub(event.target.value)}
                    placeholder="github.com/owner/repo"
                  />
                  <button className="primary" type="submit" disabled={busy || github.length < 12}>
                    Clone
                  </button>
                </form>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void runIngest(() => api.ingest(path));
                  }}
                >
                  <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="Local folder path" />
                  <button type="submit" disabled={busy || !path}>
                    Scan
                  </button>
                </form>
              </div>
            )}
            <dl className="stats">
              {(["File", "Function", "Decision", "Issue", "PullRequest", "Technology"] as const).map((label) => (
                <div key={label}>
                  <dt>{label === "PullRequest" ? "PRs" : `${label}s`}</dt>
                  <dd>{counts[label] ?? 0}</dd>
                </div>
              ))}
            </dl>
            {project.github?.url && (
              <div className="github-meta">
                <a href={project.github.url} target="_blank" rel="noreferrer">
                  {project.github.fullName || project.github.url}
                </a>
                <p>
                  {project.github.visibility ?? "public"}
                  {project.github.stars != null ? ` · ${project.github.stars} stars` : ""}
                  {project.github.language ? ` · ${project.github.language}` : ""}
                  {project.github.license ? ` · ${project.github.license}` : ""}
                </p>
              </div>
            )}
          </aside>

          <main className="stage">
            {view === "brief" && (
              <>
                <form className="ask" onSubmit={onAsk}>
                  <textarea
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    rows={2}
                    placeholder={`Ask about ${project.name}…`}
                  />
                  <div className="ask-bar">
                    <div className="seg">
                      {(["auto", "what", "why"] as Mode[]).map((item) => (
                        <button key={item} type="button" className={mode === item ? "on" : ""} onClick={() => setMode(item)}>
                          {item}
                        </button>
                      ))}
                    </div>
                    <button className="primary" type="submit" disabled={busy || !question.trim()}>
                      {busy ? "Walking graph…" : "Ask"}
                    </button>
                  </div>
                </form>

                {selected ? (
                  <BriefingCard briefing={selected} />
                ) : (
                  <p className="empty-line">No briefings yet. Ask what a function does, or why a decision was made.</p>
                )}

                {project.briefings.length > 1 && (
                  <section className="history">
                    <h2>Earlier</h2>
                    {project.briefings.slice(0, 6).map((item) => (
                      <button key={item.id} type="button" className={item.id === selected?.id ? "on" : ""} onClick={() => setSelectedId(item.id)}>
                        <span className={`stamp ${item.mode}`}>{item.mode}</span>
                        {item.headline}
                      </button>
                    ))}
                  </section>
                )}
              </>
            )}

            {view === "files" && (
              <section className="explorer">
                <header className="page-head">
                  <h1>{project.name}</h1>
                  {project.summary && <p>{project.summary}</p>}
                </header>
                {tree ? <TreeNodes nodes={tree.children} depth={0} /> : <p className="empty-line">No file tree in the graph yet.</p>}
              </section>
            )}

            {view === "memory" && (
              <section className="memory">
                <header className="page-head">
                  <h1>Graph memory</h1>
                  <p>Decisions and issues stored in Neo4j for this repository.</p>
                </header>
                <div className="cards">
                  {(project.memory?.decisions ?? []).map((item) => (
                    <article key={item.id}>
                      <span className="stamp why">decision</span>
                      <h3>{item.title}</h3>
                      <p>{item.rationale}</p>
                    </article>
                  ))}
                  {(project.memory?.issues ?? []).map((item) => (
                    <article key={item.id}>
                      <span className="stamp what">{item.key}</span>
                      <h3>{item.title}</h3>
                      <p>
                        {item.status}
                        {item.errors?.length ? ` · ${item.errors.join(", ")}` : ""}
                        {item.pulls?.length ? ` · PR ${item.pulls.join(", ")}` : ""}
                      </p>
                    </article>
                  ))}
                  {(project.memory?.decisions ?? []).length === 0 && (project.memory?.issues ?? []).length === 0 && (
                    <p className="empty-line">No decisions or issues ingested yet.</p>
                  )}
                </div>
                <form className="decision-form" onSubmit={onDecision}>
                  <h2>Record a decision</h2>
                  <input value={decisionTitle} onChange={(event) => setDecisionTitle(event.target.value)} placeholder="Title" required />
                  <textarea
                    value={decisionRationale}
                    onChange={(event) => setDecisionRationale(event.target.value)}
                    rows={3}
                    placeholder="Why the project works this way"
                    required
                  />
                  <input value={decider} onChange={(event) => setDecider(event.target.value)} placeholder="Decider (optional)" />
                  <button className="primary" type="submit" disabled={busy}>
                    Write to Neo4j
                  </button>
                </form>
              </section>
            )}
          </main>

          {showContext && selected && (
            <aside className="context">
              {selected.path && selected.path.length > 0 && (
                <>
                  <h2>Why path</h2>
                  <ol className="path">
                    {selected.path.map((item, index) => (
                      <li key={`${item.kind}-${item.name}-${index}`}>
                        <span>{item.kind}</span>
                        <b>{item.name}</b>
                      </li>
                    ))}
                  </ol>
                </>
              )}
              {selected.evidence && selected.evidence.length > 0 && (
                <>
                  <h2>Evidence</h2>
                  <ul className="evidence">
                    {selected.evidence.slice(0, 12).map((item, index) => (
                      <li key={`${item.source}-${item.relationship}-${item.target}-${index}`}>
                        <span>{item.source}</span>
                        <em>{item.relationship}</em>
                        <span>{item.target}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {selected.steps && selected.steps.length > 0 && (
                <>
                  <h2>Agent</h2>
                  <ol className="agent">
                    {selected.steps.map((step) => (
                      <li key={step.id}>
                        <b>{step.label}</b>
                        <span>{step.detail}</span>
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

function EmptyState({
  busy,
  github,
  path,
  onGithub,
  onPath,
  onGithubSubmit,
  onPathSubmit,
  onDemo,
}: {
  busy: boolean;
  github: string;
  path: string;
  onGithub: (value: string) => void;
  onPath: (value: string) => void;
  onGithubSubmit: () => void;
  onPathSubmit: () => void;
  onDemo: () => void;
}) {
  return (
    <div className="onboard">
      <div className="onboard-copy">
        <h1>Connect a repository</h1>
        <p>DevMind indexes the repo into Neo4j and answers from that graph — not from a chat transcript.</p>
      </div>
      <div className="onboard-grid">
        <form
          className="panel"
          onSubmit={(event) => {
            event.preventDefault();
            onGithubSubmit();
          }}
        >
          <h2>GitHub</h2>
          <p>Public URL, or a private repo if a token is configured.</p>
          <input value={github} onChange={(event) => onGithub(event.target.value)} placeholder="https://github.com/owner/repo" />
          <button className="primary" type="submit" disabled={busy || github.length < 12}>
            Clone and index
          </button>
        </form>
        <form
          className="panel"
          onSubmit={(event) => {
            event.preventDefault();
            onPathSubmit();
          }}
        >
          <h2>Local folder</h2>
          <p>Path on this machine. The API server must be able to read it.</p>
          <input value={path} onChange={(event) => onPath(event.target.value)} placeholder="C:\code\my-app" />
          <button type="submit" disabled={busy || !path}>
            Scan folder
          </button>
        </form>
        <div className="panel">
          <h2>Sample</h2>
          <p>Load the bundled billing-service to see decisions, issues, and a why-path.</p>
          <button type="button" disabled={busy} onClick={onDemo}>
            Index billing-service
          </button>
        </div>
      </div>
    </div>
  );
}

function BriefingCard({ briefing }: { briefing: Briefing }) {
  return (
    <article className="answer">
      <header>
        <span className={`stamp ${briefing.mode}`}>{briefing.mode}</span>
        {briefing.intent && <span className="muted">{briefing.intent.replaceAll("_", " ")}</span>}
        <time>{new Date(briefing.createdAt).toLocaleString()}</time>
      </header>
      <p className="asked">{briefing.question}</p>
      <h2>{briefing.headline}</h2>
      <div className="split">
        <section>
          <h3>What</h3>
          <ul>
            {briefing.what.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
        <section>
          <h3>Why</h3>
          {briefing.why.length > 0 ? (
            <ul>
              {briefing.why.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">No recorded rationale in the graph.</p>
          )}
        </section>
      </div>
      {briefing.gaps.length > 0 && (
        <div className="gaps">
          {briefing.gaps.map((gap) => (
            <p key={gap}>{gap}</p>
          ))}
        </div>
      )}
      {briefing.citations && briefing.citations.length > 0 && (
        <div className="cites">
          {briefing.citations.slice(0, 8).map((item) => (
            <span key={`${item.kind}-${item.name}-${item.path}`}>
              {item.path}
              {item.line ? `:${item.line}` : ""}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}

function TreeNodes({ nodes, depth }: { nodes: TreeNode[]; depth: number }) {
  const ordered = [...nodes].sort((a, b) => {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  return (
    <ul className="tree">
      {ordered.map((node) => (
        <li key={node.path}>
          <span style={{ paddingLeft: depth * 14 }} className={node.type}>
            {node.type === "dir" ? `${node.name || "/"}/` : node.name}
          </span>
          {node.children.length > 0 && <TreeNodes nodes={node.children} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}
