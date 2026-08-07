import {
  IconChat,
  IconRetriever,
  IconChevron,
  IconPlus,
  IconIngest,
  IconLibrary
} from './Icons.jsx'

/**
 * Four sections, each owning exactly one icon.
 *
 * The icon column is the sidebar's fixed spine and is always on screen. Opening
 * the panel widens the aside to the right of it; the icons do not move, and the
 * label a user was already looking at simply arrives beside its icon. Before
 * this the rail and the panel each drew their own copy of the same four icons,
 * so opening the panel put a second Chat icon at a different height from the
 * first and the eye had to work out which one it was being shown.
 *
 * Sections are the height of their contents rather than an equal share of the
 * column, so expanding one pushes the sections below it down and takes their
 * icons with it. That is what keeps an icon and its content joined: whatever is
 * open sits directly under the icon it belongs to.
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
  job,
  onCollapse
}) {
  const indexed = health?.chunk_count ?? 0
  const ingesting = job && job.phase !== 'done' && job.phase !== 'failed'

  /** The icon: always visible, always in the same place. Selects the view. */
  const Spine = ({ id, label, children }) => (
    <button
      className="tab-icon"
      onClick={() => setView(id)}
      // Only useful collapsed; open, the label beside it says the same thing.
      title={open ? undefined : label}
      aria-label={label}
    >
      <span className="tab-icon-box">{children}</span>
    </button>
  )

  /** The name and the disclosure arrow. Clipped away when the panel is shut. */
  const Toggle = ({ id, label }) => (
    <button
      className="tab-toggle"
      onClick={() => toggleTab(id)}
      aria-expanded={!!openTabs[id]}
      tabIndex={open ? 0 : -1}
    >
      <span className="tab-name">{label}</span>
      <IconChevron width={13} height={13} className="tab-chevron" />
    </button>
  )

  const cls = (id) =>
    `tab ${openTabs[id] ? 'is-open' : ''} ${view === id ? 'is-current' : ''}`

  return (
    <aside className={`sidebar ${open ? '' : 'is-collapsed'}`} aria-label="Sections">
      <div className="sidebar-sections">
        {/* ── Chat ──────────────────────────────────────────────────────── */}
        <section className={cls('chat')}>
          <h2 className="tab-head">
            <Spine id="chat" label="Chat">
              <IconChat width={20} height={20} />
            </Spine>
            <Toggle id="chat" label="Chat" />
            <button
              className="tab-action"
              onClick={onNewThread}
              title="New thread"
              aria-label="New thread"
              tabIndex={open ? 0 : -1}
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

        {/* ── Ingest ────────────────────────────────────────────────────── */}
        <section className={cls('ingest')}>
          <h2 className="tab-head">
            <Spine id="ingest" label="Ingest">
              <IconIngest width={20} height={20} />
            </Spine>
            <Toggle id="ingest" label="Ingest" />
            {ingesting && <span className="tab-live" title="Indexing" aria-label="Indexing" />}
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

            {ingesting && (
              <p className="ingest-mini eyebrow">
                {job.chunks_total
                  ? `${Math.round((job.chunks_done / job.chunks_total) * 100)}% · ${job.current}`
                  : job.phase}
              </p>
            )}
          </div>
        </section>

        {/* ── Documents ─────────────────────────────────────────────────── */}
        <section className={cls('documents')}>
          <h2 className="tab-head">
            <Spine id="documents" label="Documents">
              <IconLibrary width={20} height={20} />
            </Spine>
            <Toggle id="documents" label="Documents" />
            <span className="tab-count eyebrow">{health?.document_count ?? 0}</span>
          </h2>

          <div className="tab-body">
            <button
              className={`ingest-shortcut ${view === 'documents' ? 'is-active' : ''}`}
              onClick={() => setView('documents')}
            >
              <span>Open the sources</span>
            </button>
            <p className="tab-note">
              Every citation in Chat is a link into the page it came from.
            </p>
          </div>
        </section>

        {/* ── Retriever ─────────────────────────────────────────────────── */}
        <section className={cls('retriever')}>
          <h2 className="tab-head">
            <Spine id="retriever" label="Retriever">
              <IconRetriever width={20} height={20} />
            </Spine>
            <Toggle id="retriever" label="Retriever" />
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
      </div>

      {/* Foot, on the same two-column grid: the state light sits in the spine
          so it survives a collapse, and the words sit beside it. */}
      <footer className="sidebar-foot">
        <div className="foot-spine" title={`${indexed} passages indexed`}>
          <span
            className={`status-dot ${health?.status === 'ok' ? '' : 'is-degraded'}`}
            aria-hidden="true"
          />
        </div>

        <span className="eyebrow foot-text">
          {health
            ? health.status === 'ok'
              ? `${health.document_count} documents indexed`
              : 'Needs attention'
            : 'Server unreachable'}
        </span>

        <button
          className="panel-collapse"
          onClick={onCollapse}
          title="Hide panel"
          aria-label="Hide panel"
          tabIndex={open ? 0 : -1}
        >
          <IconChevron width={14} height={14} />
        </button>
      </footer>
    </aside>
  )
}
