import { useEffect, useState } from 'react'
import Login from './screens/Login.jsx'
import Workspace from './screens/Workspace.jsx'
import { clearToken, restoreSession, setUnauthorizedHandler } from './lib/api.js'

export default function App() {
  // Restored during the first render rather than in an effect. Doing it in an
  // effect would paint the login screen for a frame before replacing it, so a
  // reload would flash the sign-in form at someone who is already signed in.
  const [user, setUser] = useState(restoreSession)

  function signOut() {
    clearToken()
    setUser(null)
  }

  // The server is the authority on whether the session is still good. Ours may
  // look valid — unexpired, well formed — while the secret has been rotated or
  // the account disabled underneath it. A 401 from any request means the same
  // thing regardless: back to the sign-in screen, once.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  if (!user) return <Login onAuthenticated={setUser} />
  return <Workspace user={user} onSignOut={signOut} />
}
