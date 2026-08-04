import { useState } from 'react'
import Login from './screens/Login.jsx'
import Workspace from './screens/Workspace.jsx'
import { clearToken } from './lib/api.js'

export default function App() {
  const [user, setUser] = useState(null)

  function signOut() {
    clearToken()
    setUser(null)
  }

  if (!user) return <Login onAuthenticated={setUser} />
  return <Workspace user={user} onSignOut={signOut} />
}
