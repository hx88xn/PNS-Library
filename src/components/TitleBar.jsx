import { useState } from 'react'
import Mark from './Mark.jsx'
import { IconPanel, IconSignOut, IconMinimize, IconMaximize, IconClose } from './Icons.jsx'

const isMac = typeof window !== 'undefined' && window.pdas?.platform === 'darwin'

export default function TitleBar({ user, health, sidebarOpen, onToggleSidebar, onSignOut }) {
  const [maximized, setMaximized] = useState(false)

  const connection = !health
    ? { label: 'Offline', tone: 'is-down', title: 'The server cannot be reached' }
    : health.status === 'ok'
      ? { label: health.llm_model, tone: '', title: `${health.chunk_count} chunks indexed` }
      : { label: 'Degraded', tone: 'is-warn', title: health.problems?.[0] ?? '' }

  return (
    <header className={`titlebar ${isMac ? 'is-mac' : ''}`}>
      <div className="titlebar-left">
        <button
          className="icon-btn"
          onClick={onToggleSidebar}
          title={sidebarOpen ? 'Hide panel' : 'Show panel'}
          aria-label={sidebarOpen ? 'Hide panel' : 'Show panel'}
        >
          <IconPanel />
        </button>
        <span className="titlebar-divider" />
        <Mark size={20} className="titlebar-mark" />
        <span className="titlebar-name">PDAS</span>
        <span className="titlebar-sub eyebrow">Ship Design Office</span>
      </div>

      <div className="titlebar-center">
        <span className="classification-chip eyebrow">Restricted</span>
      </div>

      <div className="titlebar-right">
        <span className={`conn eyebrow ${connection.tone}`} title={connection.title}>
          <span className="conn-dot" aria-hidden="true" />
          {connection.label}
        </span>
        <span className="titlebar-user eyebrow">{user.serviceNo}</span>
        <button className="icon-btn" onClick={onSignOut} title="Sign out" aria-label="Sign out">
          <IconSignOut />
        </button>

        {!isMac && (
          <div className="window-controls">
            <button
              className="icon-btn"
              onClick={() => window.pdas?.window.minimize()}
              aria-label="Minimise"
            >
              <IconMinimize />
            </button>
            <button
              className="icon-btn"
              onClick={async () => setMaximized(await window.pdas?.window.toggleMaximize())}
              aria-label={maximized ? 'Restore' : 'Maximise'}
            >
              <IconMaximize />
            </button>
            <button
              className="icon-btn icon-btn--danger"
              onClick={() => window.pdas?.window.close()}
              aria-label="Close"
            >
              <IconClose />
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
