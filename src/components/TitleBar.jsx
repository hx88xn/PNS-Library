import { useState } from 'react'
import Mark from './Mark.jsx'
import ModelPicker from './ModelPicker.jsx'
import { IconPanel, IconSignOut, IconMinimize, IconMaximize, IconClose } from './Icons.jsx'

// window.pdas is injected by the Electron preload and is absent in a browser.
// The minimise/maximise/close controls are the frame of a desktop window: served
// as a web page they have nothing to act on and render as three dead buttons
// beside the browser's own.
const isElectron = typeof window !== 'undefined' && Boolean(window.pdas)
const isMac = isElectron && window.pdas?.platform === 'darwin'

export default function TitleBar({
  user,
  health,
  sidebarOpen,
  onToggleSidebar,
  onSignOut,
  onModelChanged
}) {
  const [maximized, setMaximized] = useState(false)

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
        <ModelPicker health={health} onChanged={onModelChanged} />
        <span className="titlebar-user eyebrow">{user.serviceNo}</span>
        <button className="icon-btn" onClick={onSignOut} title="Sign out" aria-label="Sign out">
          <IconSignOut />
        </button>

        {isElectron && !isMac && (
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
