/**
 * Client for the PDAS backend.
 *
 * The token is held in module scope rather than localStorage: on a shared
 * terminal a session should not outlive the window.
 */

const DEFAULT_SERVER = 'http://127.0.0.1:8000'

let token = null
let serverUrl = DEFAULT_SERVER

export function setToken(value) {
  token = value
}

export function clearToken() {
  token = null
}

export function getServerUrl() {
  return serverUrl
}

export function setServerUrl(value) {
  serverUrl = (value || DEFAULT_SERVER).replace(/\/+$/, '')
  // Persistence is a convenience, not a requirement: in a browser, or if the
  // settings file cannot be written, the address still applies to this session.
  Promise.resolve(window.pdas?.settings?.set({ serverUrl })).catch(() => {})
}

/** Read the stored server address. Falls back to the default in a browser. */
export async function loadServerUrl() {
  try {
    const stored = await window.pdas?.settings?.get()
    serverUrl = stored?.serverUrl || DEFAULT_SERVER
  } catch {
    serverUrl = DEFAULT_SERVER
  }
  return serverUrl
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  let response
  try {
    response = await fetch(`${serverUrl}${path}`, {
      method,
      signal,
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      body: body ? JSON.stringify(body) : undefined
    })
  } catch (cause) {
    // A failed fetch here almost always means the server address is wrong or
    // the service is down — say that rather than surfacing "Failed to fetch".
    throw new ApiError(`Cannot reach the server at ${serverUrl}.`, 0)
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body.detail)
      .catch(() => null)
    throw new ApiError(detail || `Request failed (${response.status}).`, response.status)
  }

  return response.status === 204 ? null : response.json()
}

// ── Endpoints ────────────────────────────────────────────────────────────

export function login(serviceNo, password) {
  return request('/api/auth/login', {
    method: 'POST',
    body: { service_no: serviceNo, password }
  })
}

export function health() {
  return request('/api/health')
}

export function listChunks({ offset = 0, limit = 50, collection = 'all' } = {}, signal) {
  const params = new URLSearchParams({ offset, limit, collection })
  return request(`/api/chunks?${params}`, { signal })
}

export function search({ q, collection = 'all', limit = 50, mode = 'ranked' }, signal) {
  const params = new URLSearchParams({ q, collection, limit, mode })
  return request(`/api/search?${params}`, { signal })
}

export function collections() {
  return request('/api/collections')
}

export function documents() {
  return request('/api/documents')
}

/** Upload documents. Returns immediately with a job to poll — a large PDF
 *  takes tens of minutes, which no request should hold open. */
export async function uploadDocuments(files) {
  const body = new FormData()
  for (const file of files) body.append('files', file, file.name)

  let response
  try {
    response = await fetch(`${serverUrl}/api/ingest`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body // no Content-Type: the browser sets the multipart boundary
    })
  } catch {
    throw new ApiError(`Cannot reach the server at ${serverUrl}.`, 0)
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((b) => b.detail)
      .catch(() => null)
    throw new ApiError(detail || `Upload failed (${response.status}).`, response.status)
  }
  return response.json()
}

export function removeDocument(id) {
  return request(`/api/documents/${id}`, { method: 'DELETE' })
}

export function jobStatus(id) {
  return request(`/api/ingest/${id}`)
}

export function currentJob() {
  return request('/api/ingest')
}

/**
 * Stream a grounded answer.
 *
 * Resolves when the stream terminates. Tokens arrive through onToken as they
 * are generated; citations arrive once, after the last token.
 */
export async function chatStream(
  { message, collection = 'all', history = [] },
  { onToken, onCitations, signal } = {}
) {
  let response
  try {
    response = await fetch(`${serverUrl}/api/chat`, {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      body: JSON.stringify({ message, collection, history })
    })
  } catch {
    throw new ApiError(`Cannot reach the server at ${serverUrl}.`, 0)
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body.detail)
      .catch(() => null)
    throw new ApiError(detail || `Request failed (${response.status}).`, response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line; a partial frame stays buffered.
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      const event = parseFrame(frame)
      if (!event) continue

      if (event.name === 'token') onToken?.(event.data.text)
      else if (event.name === 'citations') onCitations?.(event.data.citations)
      else if (event.name === 'error') throw new ApiError(event.data.detail, 0)
      else if (event.name === 'done') return
    }
  }
}

function parseFrame(frame) {
  let name = 'message'
  const dataLines = []

  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }

  if (dataLines.length === 0) return null
  try {
    return { name, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
}
