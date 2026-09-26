import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, type Briefing, type Health, type ProjectDetail, type ProjectSummary, type TreeNode } from "./api";

type Mode = "auto" | "what" | "why";

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [question, setQuestion] = useState("Why are amounts stored in integer cents?");
  const [mode, setMode] = useState<Mode>("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [path, setPath] = useState("examples/billing-service");
  const [decisionTitle, setDecisionTitle] = useState("");
  const [decisionRationale, setDecisionRationale] = useState("");
  const [decider, setDecider] = useState("");

  const selected = useMemo(
    () => project?.briefings.find((item) => item.id === selectedId) ?? project?.briefings[0] ?? null,
    [project, selectedId],
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
        if (status.neo4j === "connected") {
          await refreshProjects();
        }
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  async function runIngest(action: () => Promise<{ repositoryId: string; files: number; symbols: number; decisions: number }>) {
    setBusy(true);
    setError(null);
    try {
      const report = await action();
      setNotice(`Ingested ${report.files} files, ${report.symbols} symbols, ${report.decisions} decisions.`);
      await refreshProjects(report.repositoryId);
      const status = await api.health();
      setHealth(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setBusy(false);
    }
  }

  async function onAsk(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      const briefing = await api.ask(project.id, question, mode);
      const detail = await api.project(project.id);
      setProject(detail);
      setSelectedId(briefing.id);
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
      setNotice("Decision written to the graph. Ask a why-question that uses its words.");
      const detail = await api.project(project.id);
      setProject(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not store the decision");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true" />
          <div>
            <strong>DevMind</strong>
            <em>Project memory</em>
          </div>
        </div>
        <p className="tagline">What the code does, and why the project works this way.</p>
        <div className="status">
          <span className={health?.neo4j === "connected" ? "ok" : "down"}>
            Neo4j {health?.neo4j ?? "checking"}
          </span>
          <span>Model {health?.llm ?? "off"}</span>
        </div>
      </header>

      {(error || notice || (health && health.neo4j !== "connected")) && (
        <div className="banner">
          {health && health.neo4j !== "connected" && (
            <p>Neo4j is the memory layer. Start it with <code>docker compose up -d</code>, then reload.</p>
          )}
          {error && <p className="error">{error}</p>}
          {notice && <p>{notice}</p>}
        </div>
      )}

      <div className="shell">
        <aside className="panel side">
          <section>
            <h2>Repository</h2>
            <div className="project-list">
              {projects.map((item) => (
                <button
                  key={item.id}
                  className={item.id === project?.id ? "active" : ""}
                  onClick={() => refreshProjects(item.id).catch((err: Error) => setError(err.message))}
                >
                  <strong>{item.name}</strong>
                  <span>{item.files} files</span>
                </button>
              ))}
              {projects.length === 0 && <p className="muted">No repository is in the graph yet.</p>}
            </div>
            <div className="actions">
              <button disabled={busy} onClick={() => runIngest(api.demoBilling)}>
                Load billing sample
              </button>
              <button disabled={busy} onClick={() => runIngest(api.demoSelf)}>
                Ingest DevMind
              </button>
            </div>
            <form
              className="stack"
              onSubmit={(event) => {
                event.preventDefault();
                void runIngest(() => api.ingest(path));
              }}
            >
              <label>
                Local path
                <input value={path} onChange={(event) => setPath(event.target.value)} />
              </label>
              <button type="submit" disabled={busy}>
                Ingest path
              </button>
            </form>
          </section>

          {project && (
            <section>
              <h2>Graph inventory</h2>
              <dl className="inventory">
                {Object.entries(project.inventory.counts).map(([label, count]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{count}</dd>
                  </div>
                ))}
              </dl>
              <h3>Relationships</h3>
              <ul className="rels">
                {Object.entries(project.inventory.relationships).map(([type, count]) => (
                  <li key={type}>
                    <span>{type}</span>
                    <span>{count}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {tree && (
            <section>
              <h2>Files</h2>
              <div className="tree">
                <TreeNodes nodes={tree.children} depth={0} />
              </div>
            </section>
          )}
        </aside>

        <main className="panel briefings">
          <form className="composer" onSubmit={onAsk}>
            <div className="composer-head">
              <h2>Ask the project</h2>
              <div className="modes" role="radiogroup" aria-label="Briefing mode">
                {(["auto", "what", "why"] as Mode[]).map((item) => (
                  <label key={item} className={mode === item ? "active" : ""}>
                    <input
                      type="radio"
                      name="mode"
                      value={item}
                      checked={mode === item}
                      onChange={() => setMode(item)}
                    />
                    {item}
                  </label>
                ))}
              </div>
            </div>
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={3}
              placeholder="What does calculate_tax do?"
            />
            <div className="composer-foot">
              <p>Answers are walks on the Neo4j graph. Missing rationale stays missing.</p>
              <button type="submit" disabled={busy || !project}>
                {busy ? "Reading the graph…" : "Brief"}
              </button>
            </div>
          </form>

          {!project && (
            <div className="empty">
              <h3>Load a repository into memory</h3>
              <p>
                The billing sample has code, a superseded decision, a webhook incident, and the pull request that fixed it.
                Ask what <code>calculate_tax</code> does, then ask why the amounts are integer cents.
              </p>
            </div>
          )}

          {project && selected && <BriefingCard briefing={selected} />}

          {project && project.briefings.length > 1 && (
            <section className="history">
              <h2>Stored conversations</h2>
              <ul>
                {project.briefings.map((item) => (
                  <li key={item.id}>
                    <button className={item.id === selected?.id ? "active" : ""} onClick={() => setSelectedId(item.id)}>
                      <span className={`stamp ${item.mode}`}>{item.mode}</span>
                      <span>{item.headline}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </main>

        <aside className="panel evidence">
          <section>
            <h2>Evidence trail</h2>
            {selected ? (
              <ol className="trail">
                {selected.evidence.map((item, index) => (
                  <li key={`${item.source}-${item.relationship}-${item.target}-${index}`}>
                    <span>{item.source}</span>
                    <em>{item.relationship}</em>
                    <span>{item.target}</span>
                  </li>
                ))}
                {selected.evidence.length === 0 && <p className="muted">This briefing did not walk any relationships.</p>}
              </ol>
            ) : (
              <p className="muted">The relationships used for a briefing show up here, taken from Neo4j.</p>
            )}
            {selected && <p className="voice">Voice: {selected.voice}</p>}
          </section>

          <section>
            <h2>Record a decision</h2>
            <p className="muted">This becomes a Decision node. Later why-questions can find it by its wording.</p>
            <form className="stack" onSubmit={onDecision}>
              <label>
                Title
                <input value={decisionTitle} onChange={(event) => setDecisionTitle(event.target.value)} required />
              </label>
              <label>
                Rationale
                <textarea
                  value={decisionRationale}
                  onChange={(event) => setDecisionRationale(event.target.value)}
                  rows={4}
                  required
                />
              </label>
              <label>
                Decider
                <input value={decider} onChange={(event) => setDecider(event.target.value)} />
              </label>
              <button type="submit" disabled={busy || !project}>
                Write to graph
              </button>
            </form>
          </section>
        </aside>
      </div>
    </div>
  );
}

function BriefingCard({ briefing }: { briefing: Briefing }) {
  return (
    <article className="briefing">
      <header>
        <span className={`stamp ${briefing.mode}`}>{briefing.mode}</span>
        <time>{new Date(briefing.createdAt).toLocaleString()}</time>
      </header>
      <p className="question">{briefing.question}</p>
      <h3>{briefing.headline}</h3>
      <div className="columns">
        <section>
          <h4>What</h4>
          <ul>
            {briefing.what.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
        <section>
          <h4>Why</h4>
          {briefing.why.length > 0 ? (
            <ul>
              {briefing.why.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">No rationale was retrieved.</p>
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
    </article>
  );
}

function TreeNodes({ nodes, depth }: { nodes: TreeNode[]; depth: number }) {
  const ordered = [...nodes].sort((a, b) => {
    if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  return (
    <ul>
      {ordered.map((node) => (
        <li key={node.path}>
          <span style={{ paddingLeft: depth * 12 }} className={node.type}>
            {node.type === "dir" ? node.name || "/" : node.name}
          </span>
          {node.children.length > 0 && <TreeNodes nodes={node.children} depth={depth + 1} />}
        </li>
      ))}
    </ul>
  );
}
