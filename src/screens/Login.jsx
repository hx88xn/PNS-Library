import { useEffect, useState } from 'react'
import HullLines from '../components/HullLines.jsx'
import Mark from '../components/Mark.jsx'
import WindowControls from '../components/WindowControls.jsx'
import * as api from '../lib/api.js'

export default function Login({ onAuthenticated }) {
  const [serviceNo, setServiceNo] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)

  const [server, setServer] = useState(api.getServerUrl())
  const [editingServer, setEditingServer] = useState(false)

  useEffect(() => {
    api.loadServerUrl().then(setServer)
  }, [])

  async function submit(event) {
    event.preventDefault()

    if (!serviceNo.trim()) {
      setError('Enter your service number to sign in.')
      return
    }
    if (!password) {
      setError('Enter your passphrase.')
      return
    }

    setError('')
    setChecking(true)

    try {
      api.setServerUrl(server)
      const session = await api.login(serviceNo.trim(), password)
      const who = {
        serviceNo: session.service_no,
        displayName: session.display_name,
        role: session.role
      }
      // Stored with the token, so a reload can render the workspace without
      // asking the server who this is again.
      api.setToken(session.access_token, who)
      onAuthenticated(who)
    } catch (err) {
      setError(err.message)
      setPassword('')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="login on-navy">
      <div className="login-drag" />
      {/* The window has no frame on Windows or Linux, and this screen has no
          title bar, so without these there is no way to close the application
          before signing in. */}
      <WindowControls className="window-controls--login" />

      {/* Left: the sheet. The body plan draws itself as the terminal comes up. */}
      <section className="login-plate">
        <div className="login-plate-grid" aria-hidden="true" />

        <header className="login-identity">
          <Mark size={52} />
          <div>
            <p className="eyebrow login-org">Pakistan Navy · Ship Design Office</p>
            <h1 className="login-title">
              Platform Design
              <span>Assistance System</span>
            </h1>
          </div>
        </header>

        <div className="login-figure">
          <HullLines variant="hero" />
        </div>
      </section>

      {/* Right: the gate. */}
      <section className="login-gate">
        <div className="login-form-wrap">
          <p className="eyebrow login-gate-eyebrow">Secure terminal</p>
          <h2 className="login-gate-title">Sign in</h2>
          <p className="login-gate-sub">
            Access is restricted to authorised design office personnel.
          </p>

          <form onSubmit={submit} noValidate>
            <label className="field">
              <span className="field-label eyebrow">Service number</span>
              <input
                type="text"
                value={serviceNo}
                autoFocus
                spellCheck="false"
                autoComplete="off"
                placeholder="PN-00000"
                onChange={(e) => {
                  setServiceNo(e.target.value)
                  if (error) setError('')
                }}
              />
            </label>

            <label className="field">
              <span className="field-label eyebrow">Passphrase</span>
              <div className="field-affix">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  autoComplete="new-password"
                  placeholder="••••••••"
                  onChange={(e) => {
                    setPassword(e.target.value)
                    if (error) setError('')
                  }}
                />
                <button
                  type="button"
                  className="field-affix-btn eyebrow"
                  onClick={() => setShowPassword((v) => !v)}
                >
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              </div>
            </label>

            <div className="login-row">
              {/* Empty means same-origin — a proxied deployment. Naming the
                  page's own host reads better there than a blank field. */}
              <span className="server-line eyebrow" title={server || window.location.origin}>
                Server {(server || window.location.host).replace(/^https?:\/\//, '')}
              </span>
              <button
                type="button"
                className="link-btn"
                onClick={() => setEditingServer((v) => !v)}
              >
                {editingServer ? 'Done' : 'Change'}
              </button>
            </div>

            {editingServer && (
              <label className="field field--tight">
                <span className="field-label eyebrow">Server address</span>
                <input
                  type="text"
                  value={server}
                  spellCheck="false"
                  autoComplete="off"
                  placeholder="http://10.0.0.5:8000"
                  onChange={(e) => setServer(e.target.value)}
                />
              </label>
            )}

            <p className={`form-error ${error ? 'is-shown' : ''}`} role="alert">
              {error}
            </p>

            <button type="submit" className="btn-primary" disabled={checking}>
              {checking ? 'Verifying credentials' : 'Sign in'}
              {checking && <span className="btn-spinner" aria-hidden="true" />}
            </button>
          </form>

          <p className="login-note">
            Sessions are logged. Sign out before leaving the terminal unattended.
          </p>
        </div>
      </section>
    </div>
  )
}
