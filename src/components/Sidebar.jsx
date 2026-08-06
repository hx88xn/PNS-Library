import { IconChat, IconRetriever, IconChevron, IconPlus, IconIngest } from './Icons.jsx'

/**
 * Two tabs, each of which opens and closes on its own.
 * Opening one makes it the active view; closing both leaves the rail alone.
 */
export default function Sidebar({
  open,
  view,
  setView,
  openTabs,
  toggleTab,
  threads,
  activeThread,
  onSelectThread,
  onNewThread,
  collection,
  setCollection,
  collections,
  health,
  job
}) {
  const indexed = health?.chunk_count ?? 0

  return (
    <aside className={`sidebar ${open ? '' : 'is-collapsed'}`}>
      {/* Rail — always reachable, even with both tabs closed */}
      <nav className="rail" aria-label="Sections">
        <button
          className={`rail-btn ${view === 'chat' ? 'is-active' : ''}`}
          onClick={() => {
            setView('chat')
            if (!openTabs.chat) toggleTab('chat')
          }}
          title="Chat"
          aria-label="Chat"
        >
          <IconChat width={20} height={20} />
        </button>
        <button
          className={`rail-btn ${view === 'ingest' ? 'is-active' : ''}`}
          onClick={() => {
            setView('ingest')
            if (!openTabs.ingest) toggleTab('ingest')
          }}
          title="Ingest"
          aria-label="Ingest"
        >
          <IconIngest width={20} height={20} />
        </button>
        <button
          className={`rail-btn ${view === 'retriever' ? 'is-active' : ''}`}
          onClick={() => {
            setView('retriever')
            if (!openTabs.retriever) toggleTab('retriever')
          }}
          title="Retriever"
          aria-label="Retriever"
        >
          <IconRetriever width={20} height={20} />
        </button>

        <div className="rail-foot">
          <span className="rail-index eyebrow" title="Chunks in the index">
            {indexed}
          </span>
          <span className="rail-index-label eyebrow">idx</span>
        </div>
      </nav>

      {open && (
        <div className="panel">
          {/* ── Tab 1: Chat ─────────────────────────────────────────────── */}
          <section className={`tab ${openTabs.chat ? 'is-open' : ''}`}>
            <h2 className="tab-head">
              <button
                className="tab-toggle"
                onClick={() => {
                  toggleTab('chat')
                  setView('chat')
                }}
                aria-expanded={openTabs.chat}
              >
                <IconChevron width={14} height={14} className="tab-chevron" />
                <IconChat width={15} height={15} />
                <span>Chat</span>
              </button>
              <button
                className="tab-action"
                onClick={onNewThread}
                title="New thread"
                aria-label="New thread"
              >
                <IconPlus width={15} height={15} />
              </button>
            </h2>

            <div className="tab-body">
              <ul className="thread-list">
                {threads.map((t) => (
                  <li key={t.id}>
                    <button
                      className={`thread ${
                        t.id === activeThread && view === 'chat' ? 'is-active' : ''
                      }`}
                      onClick={() => {
                        onSelectThread(t.id)
                        setView('chat')
                      }}
                    >
                      <span className="thread-title">{t.title}</span>
                      <span className="thread-meta eyebrow">{t.when}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          {/* ── Tab 2: Ingest ───────────────────────────────────────────── */}
          <section className={`tab ${openTabs.ingest ? 'is-open' : ''}`}>
            <h2 className="tab-head">
              <button
                className="tab-toggle"
                onClick={() => {
                  toggleTab('ingest')
                  setView('ingest')
                }}
                aria-expanded={openTabs.ingest}
              >
                <IconChevron width={14} height={14} className="tab-chevron" />
                <IconIngest width={15} height={15} />
                <span>Ingest</span>
              </button>
              {job && job.phase !== 'done' && job.phase !== 'failed' && (
                <span className="tab-live" title="Indexing" aria-label="Indexing" />
              )}
            </h2>

            <div className="tab-body">
              <button
                className={`ingest-shortcut ${view === 'ingest' ? 'is-active' : ''}`}
                onClick={() => setView('ingest')}
              >
                <span>Add documents</span>
              </button>

              <dl className="ingest-facts">
                <div>
                  <dt>Documents</dt>
                  <dd>{health?.document_count ?? '—'}</dd>
                </div>
                <div>
                  <dt>Passages</dt>
                  <dd>{indexed}</dd>
                </div>
              </dl>

              {job && job.phase !== 'done' && job.phase !== 'failed' && (
                <p className="ingest-mini eyebrow">
                  {job.chunks_total
                    ? `${Math.round((job.chunks_done / job.chunks_total) * 100)}% · ${job.current}`
                    : job.phase}
                </p>
              )}
            </div>
          </section>

          {/* ── Tab 3: Retriever ────────────────────────────────────────── */}
          <section className={`tab ${openTabs.retriever ? 'is-open' : ''}`}>
            <h2 className="tab-head">
              <button
                className="tab-toggle"
                onClick={() => {
                  toggleTab('retriever')
                  setView('retriever')
                }}
                aria-expanded={openTabs.retriever}
              >
                <IconChevron width={14} height={14} className="tab-chevron" />
                <IconRetriever width={15} height={15} />
                <span>Retriever</span>
              </button>
              <span className="tab-count eyebrow">{indexed}</span>
            </h2>

            <div className="tab-body">
              <ul className="collection-list">
                <li>
                  <button
                    className={`collection ${collection === 'all' ? 'is-active' : ''}`}
                    onClick={() => {
                      setCollection('all')
                      setView('retriever')
                    }}
                  >
                    <span>All documents</span>
                    <span className="collection-count eyebrow">{indexed}</span>
                  </button>
                </li>
                {collections.map((c) => (
                  <li key={c.id}>
                    <button
                      className={`collection ${collection === c.id ? 'is-active' : ''}`}
                      onClick={() => {
                        setCollection(c.id)
                        setView('retriever')
                      }}
                    >
                      <span>{c.label}</span>
                      <span className="collection-count eyebrow">{c.count}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <footer className="panel-foot">
            <span
              className={`status-dot ${health?.status === 'ok' ? '' : 'is-degraded'}`}
              aria-hidden="true"
            />
            <span className="eyebrow">
              {health
                ? health.status === 'ok'
                  ? `${health.document_count} documents indexed`
                  : 'Needs attention'
                : 'Server unreachable'}
            </span>
          </footer>
        </div>
      )}
    </aside>
  )
}
