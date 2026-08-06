import { useCallback, useEffect, useRef, useState } from 'react'
import { IconDoc, IconClose } from '../components/Icons.jsx'
import * as api from '../lib/api.js'

const POLL_MS = 900
const ACCEPT = '.pdf,.docx,.xlsx,.dxf'

const FORMATS = [
  { ext: 'PDF', note: 'digital text layer' },
  { ext: 'DOCX', note: 'headings drive sections' },
  { ext: 'XLSX', note: 'row-wise' },
  { ext: 'DXF', note: 'title block + layers' }
]

function duration(seconds) {
  if (!seconds || seconds < 1) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`
}

export default function Ingest({ onIndexChanged }) {
  const [job, setJob] = useState(null)
  const [documents, setDocuments] = useState([])
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [removing, setRemoving] = useState(null)

  const inputRef = useRef(null)
  const wasRunning = useRef(false)

  const loadDocuments = useCallback(async () => {
    try {
      setDocuments(await api.documents())
    } catch {
      /* the panel still works without the library list */
    }
  }, [])

  useEffect(() => {
    loadDocuments()
    api.currentJob().then((d) => setJob(d.job)).catch(() => {})
  }, [loadDocuments])

  // Poll while a job is live. Stop as soon as it settles, so an idle panel
  // isn't hitting the server every second for nothing.
  useEffect(() => {
    const running = job && job.phase !== 'done' && job.phase !== 'failed'
    if (!running) {
      if (wasRunning.current) {
        wasRunning.current = false
        loadDocuments()
        onIndexChanged?.()
      }
      return
    }
    wasRunning.current = true

    const timer = setTimeout(async () => {
      try {
        setJob(await api.jobStatus(job.id))
      } catch {
        /* transient; the next tick retries */
      }
    }, POLL_MS)
    return () => clearTimeout(timer)
  }, [job, loadDocuments, onIndexChanged])

  async function remove(doc) {
    const label = doc.title || doc.filename
    if (!window.confirm(
      `Remove "${label}" from the index?\n\n` +
      `${doc.chunk_count} passage(s) go, and the vector index is rebuilt from ` +
      `what remains. The original file is not touched.`
    )) return

    setError('')
    setRemoving(doc.id)
    try {
      await api.removeDocument(doc.id)
      await loadDocuments()
      onIndexChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setRemoving(null)
    }
  }

  async function send(fileList) {
    const files = Array.from(fileList || [])
    if (files.length === 0) return

    setError('')
    setUploading(true)
    try {
      const data = await api.uploadDocuments(files)
      setJob(data.job)
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const running = job && job.phase !== 'done' && job.phase !== 'failed'
  const pct =
    job && job.chunks_total
      ? Math.min(100, Math.round((job.chunks_done / job.chunks_total) * 100))
      : 0

  return (
    <div className="ingest">
      <div className="ingest-scroll">
        {/* ── Drop zone ─────────────────────────────────────────────── */}
        <section
          className={`dropzone ${dragging ? 'is-over' : ''} ${running ? 'is-busy' : ''}`}
          onDragOver={(e) => {
            e.preventDefault()
            if (!running) setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            if (!running) send(e.dataTransfer.files)
          }}
        >
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            onChange={(e) => send(e.target.files)}
          />

          <div className="dropzone-mark" aria-hidden="true">
            <svg viewBox="0 0 48 48" fill="none">
              <path
                className="dz-tray"
                d="M8 30v6a4 4 0 0 0 4 4h24a4 4 0 0 0 4-4v-6"
              />
              <path className="dz-arrow" d="M24 32V10" />
              <path className="dz-arrow" d="M15 19l9-9 9 9" />
            </svg>
          </div>

          <h2 className="dropzone-title">
            {running ? 'Indexing in progress' : 'Add documents to the library'}
          </h2>
          <p className="dropzone-sub">
            {running
              ? 'Wait for this to finish before adding more.'
              : 'Drop files here, or choose them.'}
          </p>

          <button
            className="btn-primary dropzone-btn"
            onClick={() => inputRef.current?.click()}
            disabled={running || uploading}
          >
            {uploading ? 'Uploading' : 'Choose files'}
          </button>

          <ul className="format-list">
            {FORMATS.map((f) => (
              <li key={f.ext}>
                <span className="format-ext eyebrow">{f.ext}</span>
                <span className="format-note">{f.note}</span>
              </li>
            ))}
          </ul>

          <p className="dropzone-warn eyebrow">
            DWG is not readable — convert to DXF or plot to PDF. Scanned pages
            need OCR first.
          </p>
        </section>

        {error && (
          <div className="ingest-error" role="alert">
            <span className="eyebrow">Rejected</span>
            <span>{error}</span>
            <button className="icon-btn-sm" onClick={() => setError('')} aria-label="Dismiss">
              <IconClose width={14} height={14} />
            </button>
          </div>
        )}

        {/* ── Live job ──────────────────────────────────────────────── */}
        {job && (
          <section className={`job ${job.phase}`}>
            <header className="job-head">
              <div>
                <p className="eyebrow job-phase">
                  {job.phase === 'done'
                    ? 'Complete'
                    : job.phase === 'failed'
                      ? 'Failed'
                      : job.phase}
                </p>
                <h3 className="job-title">
                  {running && job.current ? job.current : `${job.files.length} document${job.files.length === 1 ? '' : 's'}`}
                </h3>
              </div>

              <dl className="job-stats">
                <div>
                  <dt className="eyebrow">Chunks</dt>
                  <dd>{job.totals.chunks || job.chunks_done}</dd>
                </div>
                {running && (
                  <>
                    <div>
                      <dt className="eyebrow">Rate</dt>
                      <dd>{job.rate}<span className="unit">/s</span></dd>
                    </div>
                    <div>
                      <dt className="eyebrow">Remaining</dt>
                      <dd>{duration(job.eta_seconds)}</dd>
                    </div>
                  </>
                )}
                {!running && (
                  <div>
                    <dt className="eyebrow">Took</dt>
                    <dd>{duration(job.elapsed_seconds)}</dd>
                  </div>
                )}
              </dl>
            </header>

            {running && (
              <div className="progress" role="progressbar" aria-valuenow={pct}>
                <span className="progress-fill" style={{ width: `${pct}%` }} />
                <span className="progress-label eyebrow">
                  {job.chunks_total
                    ? `${job.chunks_done} / ${job.chunks_total} chunks`
                    : 'reading the document'}
                </span>
              </div>
            )}

            {job.error && <p className="job-error">{job.error}</p>}

            <ul className="job-files">
              {job.files.map((f) => (
                <li key={f.name} className={`job-file is-${f.status}`}>
                  <span className={`file-dot is-${f.status}`} aria-hidden="true" />
                  <IconDoc width={14} height={14} />
                  <span className="file-name">{f.name}</span>
                  {f.pages != null && <span className="file-meta eyebrow">{f.pages}p</span>}
                  {f.chunks > 0 && (
                    <span className="file-meta eyebrow">{f.chunks} chunks</span>
                  )}
                  {f.detail && <span className="file-detail">{f.detail}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ── The library ───────────────────────────────────────────── */}
        <section className="library">
          <header className="library-head">
            <h3 className="library-title">In the library</h3>
            <span className="library-count eyebrow">
              {documents.length} document{documents.length === 1 ? '' : 's'}
            </span>
          </header>

          {documents.length === 0 ? (
            <p className="library-empty">
              Nothing indexed yet. Anything added here becomes searchable in the
              Retriever and citable in Chat.
            </p>
          ) : (
            <table className="library-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Reference</th>
                  <th className="num">Pages</th>
                  <th className="num">Chunks</th>
                  <th>Collection</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr key={d.id} className={d.status === 'failed' ? 'is-failed' : ''}>
                    <td className="doc-name" title={d.filename}>
                      {d.title || d.filename}
                    </td>
                    <td className="doc-ref">{d.doc_ref || '—'}</td>
                    <td className="num">{d.pages ?? '—'}</td>
                    <td className="num">{d.chunk_count}</td>
                    <td>
                      <span className="doc-collection">{d.collection}</span>
                    </td>
                    <td>
                      <span className={`doc-status is-${d.status}`}>{d.status}</span>
                      {d.error && <span className="doc-error" title={d.error}>{d.error}</span>}
                    </td>
                    <td className="doc-actions">
                      <button
                        className="doc-remove"
                        disabled={removing === d.id}
                        onClick={() => remove(d)}
                        title="Remove from the index"
                        aria-label={`Remove ${d.filename}`}
                      >
                        {removing === d.id ? '…' : <IconClose width={13} height={13} />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  )
}
