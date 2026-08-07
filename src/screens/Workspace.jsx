import { useCallback, useEffect, useState } from 'react'
import TitleBar from '../components/TitleBar.jsx'
import Sidebar from '../components/Sidebar.jsx'
import Chat from '../views/Chat.jsx'
import Retriever from '../views/Retriever.jsx'
import Ingest from '../views/Ingest.jsx'
import Documents from '../views/Documents.jsx'
import * as api from '../lib/api.js'

let nextId = 2

const JOB_POLL_MS = 900

const STAGE = {
  chat: {
    title: 'Chat',
    sub: 'Design questions answered from the office library, with citations.'
  },
  ingest: {
    title: 'Ingest',
    sub: 'Add documents to the library. Parsed, chunked and indexed for retrieval.'
  },
  documents: {
    title: 'Documents',
    sub: 'The sources themselves. Open a citation to land on the page it came from.'
  },
  retriever: {
    title: 'Retriever',
    sub: 'Every indexed passage in the library. Search to narrow it.'
  }
}

export default function Workspace({ user, onSignOut }) {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [view, setView] = useState('chat')
  const [openTabs, setOpenTabs] = useState({
    chat: true,
    ingest: true,
    retriever: true,
    documents: true
  })
  const [threads, setThreads] = useState([
    { id: 1, title: 'New thread', when: 'Now', messages: [] }
  ])
  const [activeThread, setActiveThread] = useState(1)
  const [collection, setCollection] = useState('all')
  const [collections, setCollections] = useState([])
  const [health, setHealth] = useState(null)
  const [job, setJob] = useState(null)
  // What the Documents tab should open: set by a citation click, cleared once
  // the viewer has honoured it.
  const [target, setTarget] = useState(null)

  const thread = threads.find((t) => t.id === activeThread) ?? threads[0]

  const refresh = useCallback(async () => {
    try {
      const [cols, status] = await Promise.all([api.collections(), api.health()])
      setCollections(cols)
      setHealth(status)
    } catch {
      setHealth(null)
    }
  }, [])

  useEffect(() => {
    refresh()
    api.currentJob().then((d) => setJob(d.job)).catch(() => {})
  }, [refresh])

  // Ingest progress is polled HERE, not inside the Ingest view, because the
  // view unmounts the moment you switch tabs. The work itself always ran on
  // the server -- what used to be lost was the client's knowledge of it, so
  // leaving the tab looked like abandoning the ingest. Polling from the
  // workspace means the job keeps ticking in the sidebar from any tab, and
  // returning to Ingest shows it mid-flight rather than starting cold.
  useEffect(() => {
    if (!job) return
    if (job.phase === 'done' || job.phase === 'failed') return

    const timer = setTimeout(async () => {
      try {
        const next = await api.jobStatus(job.id)
        setJob(next)
        if (next.phase === 'done' || next.phase === 'failed') refresh()
      } catch {
        /* transient; the next tick retries */
      }
    }, JOB_POLL_MS)
    return () => clearTimeout(timer)
  }, [job, refresh])

  /** Open a cited passage in the Documents tab, at its page. */
  const openCitation = useCallback((citation) => {
    if (!citation?.document_id) return
    setTarget({
      documentId: citation.document_id,
      page: citation.page,
      chunkId: citation.id,
      at: Date.now()   // makes a repeat click on the same citation re-navigate
    })
    setView('documents')
    setOpenTabs((prev) => (prev.documents ? prev : { ...prev, documents: true }))
  }, [])

  function toggleTab(name) {
    setOpenTabs((prev) => ({ ...prev, [name]: !prev[name] }))
  }

  function newThread() {
    const id = nextId++
    setThreads((prev) => [{ id, title: 'New thread', when: 'Now', messages: [] }, ...prev])
    setActiveThread(id)
    setView('chat')
    if (!openTabs.chat) toggleTab('chat')
  }

  function appendMessage(message) {
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeThread) return t
        const title =
          t.messages.length === 0 && message.role === 'user'
            ? message.text.slice(0, 46) + (message.text.length > 46 ? '…' : '')
            : t.title
        return { ...t, messages: [...t.messages, message], title }
      })
    )
  }

  /** Patch the message being streamed, token by token. */
  function patchLastMessage(patch) {
    setThreads((prev) =>
      prev.map((t) => {
        if (t.id !== activeThread || t.messages.length === 0) return t
        const messages = t.messages.slice()
        messages[messages.length - 1] = { ...messages[messages.length - 1], ...patch }
        return { ...t, messages }
      })
    )
  }

  return (
    <div className="workspace">
      <TitleBar
        user={user}
        health={health}
        sidebarOpen={sidebarOpen}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        onSignOut={onSignOut}
        onModelChanged={refresh}
      />

      <div className="workspace-body">
        <Sidebar
          open={sidebarOpen}
          view={view}
          setView={setView}
          openTabs={openTabs}
          toggleTab={toggleTab}
          threads={threads}
          activeThread={activeThread}
          onSelectThread={setActiveThread}
          onNewThread={newThread}
          collection={collection}
          setCollection={setCollection}
          collections={collections}
          health={health}
          job={job}
          onCollapse={() => setSidebarOpen(false)}
        />

        <main className="stage">
          <div className="stage-head">
            <h1 className="stage-title">
              {STAGE[view].title}
            </h1>
            <p className="stage-sub">
              {STAGE[view].sub}
            </p>
          </div>

          {health?.problems?.length > 0 && (
            <div className="banner" role="status">
              <span className="banner-label eyebrow">Attention</span>
              <span className="banner-text">{health.problems[0]}</span>
              <button className="banner-action eyebrow" onClick={refresh}>
                Recheck
              </button>
            </div>
          )}

          {view === 'chat' ? (
            <Chat
              key={thread.id}
              thread={thread}
              collection={collection}
              onSend={appendMessage}
              onPatchLast={patchLastMessage}
              onOpenCitation={openCitation}
            />
          ) : view === 'ingest' ? (
            <Ingest job={job} setJob={setJob} onIndexChanged={refresh} />
          ) : view === 'documents' ? (
            <Documents target={target} onConsumeTarget={() => setTarget(null)} />
          ) : (
            <Retriever
              collection={collection}
              setCollection={setCollection}
              collections={collections}
            />
          )}
        </main>
      </div>
    </div>
  )
}
