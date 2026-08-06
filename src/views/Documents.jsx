import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { IconDoc, IconChevron, IconSearch } from '../components/Icons.jsx'
import { openDocument } from '../lib/pdf.js'
import * as api from '../lib/api.js'

/**
 * The sources themselves.
 *
 * One page is rendered at a time rather than a continuous scroll. A merged
 * rulebook runs to fifteen hundred pages; a scroller over that needs
 * virtualisation, placeholder sizing and scroll anchoring to behave, and every
 * one of those is a way for "jump to page 197" to land somewhere else. A
 * single page cannot miss. The main use here is arriving from a citation and
 * checking one figure, which is a page at a time anyway.
 */
export default function Documents({ target, onConsumeTarget }) {
  const [documents, setDocuments] = useState([])
  const [selected, setSelected] = useState(null)
  const [pdf, setPdf] = useState(null)
  const [text, setText] = useState(null)
  const [page, setPage] = useState(1)
  const [pageDraft, setPageDraft] = useState('1')
  const [zoom, setZoom] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')

  const canvasRef = useRef(null)
  const scrollRef = useRef(null)
  // The in-flight render task. pdf.js rejects if you start a second render on
  // the same canvas, so the previous one is cancelled first.
  const renderRef = useRef(null)
  // The pdf.js loading task, kept because only it can destroy the document.
  const taskRef = useRef(null)

  useEffect(() => {
    api.documents().then(setDocuments).catch((err) => setError(err.message))
  }, [])

  // ── Loading a document ────────────────────────────────────────────────

  const load = useCallback(async (doc, startPage) => {
    setSelected(doc)
    setError('')
    setText(null)
    setPdf(null)
    setLoading(true)

    // Close the previous document explicitly. Each one holds a worker and the
    // decoded page cache; on a fifteen-hundred-page book that is real memory.
    renderRef.current?.cancel()
    if (taskRef.current) {
      taskRef.current.destroy().catch(() => {})
      taskRef.current = null
    }

    try {
      if (doc.format === 'pdf') {
        const bytes = await api.documentFile(doc.id)
        const task = openDocument(new Uint8Array(bytes))
        taskRef.current = task
        const opened = await task.promise
        setPdf(opened)
        const first = clamp(startPage ?? 1, 1, opened.numPages)
        setPage(first)
        setPageDraft(String(first))
      } else {
        // No renderer worth shipping offline for DOCX/XLSX/DXF, so show what
        // was actually indexed — which is the text retrieval searches anyway.
        const body = await api.documentText(doc.id)
        setText(body.text)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    return () => {
      renderRef.current?.cancel()
      taskRef.current?.destroy().catch(() => {})
    }
  }, [])

  // ── Arriving from a citation ──────────────────────────────────────────

  useEffect(() => {
    if (!target || documents.length === 0) return

    const doc = documents.find((d) => d.id === target.documentId)
    if (!doc) {
      setError('That document is no longer in the library.')
      onConsumeTarget?.()
      return
    }

    if (selected?.id === doc.id && pdf) {
      const next = clamp(target.page ?? 1, 1, pdf.numPages)
      setPage(next)
      setPageDraft(String(next))
    } else {
      load(doc, target.page)
    }
    onConsumeTarget?.()
    // `target.at` changes on every citation click, so clicking the same one
    // twice navigates twice.
  }, [target?.at, documents]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Rendering the page ────────────────────────────────────────────────

  useEffect(() => {
    if (!pdf) return
    let cancelled = false

    ;(async () => {
      try {
        const rendered = await pdf.getPage(page)
        if (cancelled) return

        const canvas = canvasRef.current
        if (!canvas) return

        // Fit the width of the scroller, then apply zoom. Rendered at device
        // pixel ratio so small type in a scantling table stays legible.
        const base = rendered.getViewport({ scale: 1 })
        const available = (scrollRef.current?.clientWidth ?? 900) - 56
        const ratio = window.devicePixelRatio || 1
        const viewport = rendered.getViewport({
          scale: ((available / base.width) * zoom) || 1
        })

        canvas.width = Math.floor(viewport.width * ratio)
        canvas.height = Math.floor(viewport.height * ratio)
        canvas.style.width = `${Math.floor(viewport.width)}px`
        canvas.style.height = `${Math.floor(viewport.height)}px`

        renderRef.current?.cancel()
        // `canvas`, not `canvasContext`: the latter is deprecated in pdf.js 6.
        const task = rendered.render({
          canvas,
          viewport,
          transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0]
        })
        renderRef.current = task
        await task.promise
        if (!cancelled) scrollRef.current?.scrollTo({ top: 0 })
      } catch (err) {
        // A cancelled render is the expected outcome of paging quickly.
        if (!cancelled && err?.name !== 'RenderingCancelledException') {
          setError(err.message)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [pdf, page, zoom])

  function go(next) {
    if (!pdf) return
    const clamped = clamp(next, 1, pdf.numPages)
    setPage(clamped)
    setPageDraft(String(clamped))
  }

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return documents
    return documents.filter((d) =>
      `${d.title ?? ''} ${d.filename} ${d.doc_ref ?? ''}`.toLowerCase().includes(needle)
    )
  }, [documents, filter])

  return (
    <div className="docs">
      {/* ── The shelf ───────────────────────────────────────────────── */}
      <aside className="docs-shelf">
        <div className="docs-filter">
          <IconSearch width={14} height={14} />
          <input
            type="text"
            value={filter}
            placeholder="Filter documents"
            spellCheck="false"
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        {documents.length === 0 ? (
          <p className="docs-empty">Nothing in the library yet.</p>
        ) : (
          <ul className="docs-list">
            {shown.map((d) => (
              <li key={d.id}>
                <button
                  className={`docs-item ${selected?.id === d.id ? 'is-active' : ''}`}
                  onClick={() => load(d)}
                >
                  <IconDoc width={15} height={15} />
                  <span className="docs-item-body">
                    <span className="docs-item-name">{d.title || d.filename}</span>
                    <span className="docs-item-meta eyebrow">
                      {d.format}
                      {d.pages != null && ` · ${d.pages} pages`}
                      {` · ${d.chunk_count} passages`}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* ── The viewer ──────────────────────────────────────────────── */}
      <section className="docs-view">
        {!selected ? (
          <div className="docs-blank">
            <IconDoc width={30} height={30} />
            <p>Choose a document, or click a citation in Chat to land on its page.</p>
          </div>
        ) : (
          <>
            <header className="docs-bar">
              <div className="docs-bar-id">
                <h3 className="docs-bar-name">{selected.title || selected.filename}</h3>
                {selected.doc_ref && (
                  <span className="docs-bar-ref eyebrow">{selected.doc_ref}</span>
                )}
              </div>

              {pdf && (
                <div className="docs-nav">
                  <button
                    className="docs-step"
                    onClick={() => go(page - 1)}
                    disabled={page <= 1}
                    aria-label="Previous page"
                  >
                    <IconChevron width={13} height={13} className="rot-90" />
                  </button>

                  <form
                    className="docs-page"
                    onSubmit={(e) => {
                      e.preventDefault()
                      const n = parseInt(pageDraft, 10)
                      if (Number.isFinite(n)) go(n)
                      else setPageDraft(String(page))
                    }}
                  >
                    <input
                      value={pageDraft}
                      inputMode="numeric"
                      aria-label="Page number"
                      onChange={(e) => setPageDraft(e.target.value)}
                      onBlur={() => setPageDraft(String(page))}
                    />
                    <span className="docs-page-total eyebrow">/ {pdf.numPages}</span>
                  </form>

                  <button
                    className="docs-step"
                    onClick={() => go(page + 1)}
                    disabled={page >= pdf.numPages}
                    aria-label="Next page"
                  >
                    <IconChevron width={13} height={13} className="rot-270" />
                  </button>

                  <div className="docs-zoom">
                    <button
                      onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))}
                      disabled={zoom <= 0.5}
                      aria-label="Zoom out"
                    >
                      −
                    </button>
                    <span className="eyebrow">{Math.round(zoom * 100)}%</span>
                    <button
                      onClick={() => setZoom((z) => Math.min(3, +(z + 0.25).toFixed(2)))}
                      disabled={zoom >= 3}
                      aria-label="Zoom in"
                    >
                      +
                    </button>
                  </div>
                </div>
              )}
            </header>

            {error && <p className="docs-error">{error}</p>}

            <div className="docs-stage" ref={scrollRef}>
              {loading ? (
                <div className="docs-loading">
                  <span className="sounding" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                  <span className="eyebrow">Opening {selected.filename}</span>
                </div>
              ) : text !== null ? (
                <pre className="docs-text">{text || 'No text was stored for this document.'}</pre>
              ) : (
                <canvas ref={canvasRef} className="docs-canvas" />
              )}
            </div>
          </>
        )}
      </section>
    </div>
  )
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value))
}
