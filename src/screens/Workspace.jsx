import { useCallback, useEffect, useState } from 'react'
import TitleBar from '../components/TitleBar.jsx'
import Sidebar from '../components/Sidebar.jsx'
import Chat from '../views/Chat.jsx'
import Retriever from '../views/Retriever.jsx'
import Ingest from '../views/Ingest.jsx'
import * as api from '../lib/api.js'

let nextId = 2

export default function Workspace({ user, onSignOut }) {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [view, setView] = useState('chat')
  const [openTabs, setOpenTabs] = useState({ chat: true, ingest: true, retriever: true })
  const [threads, setThreads] = useState([
    { id: 1, title: 'New thread', when: 'Now', messages: [] }
  ])
  const [activeThread, setActiveThread] = useState(1)
  const [collection, setCollection] = useState('all')
  const [collections, setCollections] = useState([])
  const [health, setHealth] = useState(null)
  const [job, setJob] = useState(null)

  const thread = threads.find((t) => t.id === activeThread) ?? threads[0]

  const refresh = useCallback(async () => {
    try {
      const [cols, status] = await Promise.all([api.collections(), api.health()])
      setCollections(cols)
      setHealth(status)
      api.currentJob().then((d) => setJob(d.job)).catch(() => {})
    } catch {
      setHealth(null)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

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
        />

        <main className="stage">
          <div className="stage-head">
            <h1 className="stage-title">
              {view === 'chat' ? 'Chat' : view === 'ingest' ? 'Ingest' : 'Retriever'}
            </h1>
            <p className="stage-sub">
              {view === 'chat'
                ? 'Design questions answered from the office library, with citations.'
                : view === 'ingest'
                  ? 'Add documents to the library. Parsed, chunked and indexed for retrieval.'
                  : 'Every indexed passage in the library. Search to narrow it.'}
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
            />
          ) : view === 'ingest' ? (
            <Ingest onIndexChanged={refresh} />
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
