import Mark from './Mark.jsx'
import ModelPicker from './ModelPicker.jsx'
import WindowControls from './WindowControls.jsx'
import { IconPanel, IconSignOut } from './Icons.jsx'

// macOS keeps its native traffic lights, and the title bar insets to clear
// them. Every other platform gets a frameless window — see WindowControls.
const isMac = typeof window !== 'undefined' && window.pdas?.platform === 'darwin'

export default function TitleBar({
  user,
  health,
  sidebarOpen,
  onToggleSidebar,
  onSignOut,
  onModelChanged
}) {
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
        {/* <span className="classification-chip eyebrow">Restricted</span> */}
      </div>

      <div className="titlebar-right">
        <ModelPicker health={health} onChanged={onModelChanged} />
        <span className="titlebar-user eyebrow">{user.serviceNo}</span>
        <button className="icon-btn" onClick={onSignOut} title="Sign out" aria-label="Sign out">
          <IconSignOut />
        </button>

        <WindowControls />
      </div>
    </header>
  )
}
