import { useState } from 'react'
import { IconMinimize, IconMaximize, IconClose } from './Icons.jsx'

/**
 * Minimise, maximise, close — for the platforms where the window has no frame
 * of its own.
 *
 * Shared between the title bar and the sign-in screen, and that sharing is the
 * point. main.cjs opens the window with `frame: isMac`, so on Windows and Linux
 * these three buttons are the only way to close the application. The sign-in
 * screen had no title bar and therefore no controls: a frameless window a user
 * could not close without Alt+F4, before they had even signed in.
 *
 * macOS keeps its native traffic lights, so nothing renders there.
 */
export default function WindowControls({ className = '' }) {
  const [maximized, setMaximized] = useState(false)

  // window.pdas is injected by the Electron preload and absent in a browser,
  // where these would be three dead buttons beside the browser's own.
  const pdas = typeof window !== 'undefined' ? window.pdas : undefined
  if (!pdas || pdas.platform === 'darwin') return null

  return (
    <div className={`window-controls ${className}`}>
      <button
        className="win-btn"
        onClick={() => pdas.window.minimize()}
        title="Minimise"
        aria-label="Minimise"
      >
        <IconMinimize width={15} height={15} />
      </button>
      <button
        className="win-btn"
        onClick={async () => setMaximized(await pdas.window.toggleMaximize())}
        title={maximized ? 'Restore' : 'Maximise'}
        aria-label={maximized ? 'Restore' : 'Maximise'}
      >
        <IconMaximize width={15} height={15} />
      </button>
      <button
        className="win-btn win-btn--close"
        onClick={() => pdas.window.close()}
        title="Close"
        aria-label="Close"
      >
        <IconClose width={15} height={15} />
      </button>
    </div>
  )
}
