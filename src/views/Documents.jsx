import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { IconDoc, IconChevron, IconSearch } from '../components/Icons.jsx'
import { openDocument, pdfjs } from '../lib/pdf.js'
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

  // Find-in-document. `query` is what the box holds; `find` is the result set
  // for the query that was actually run, so the highlight and the hit list
  // never describe different searches.
  const [query, setQuery] = useState('')
  const [find, setFind] = useState(null)
  const [finding, setFinding] = useState(false)
  // Matches actually painted on the page now on screen. Null when no search is
  // running, so "none found" and "not searched" stay distinguishable.
  const [onPage, setOnPage] = useState(null)

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
    setQuery('')
    setFind(null)
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
        const task = openDocument(api.documentFileSource(doc.id))
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

  // ── Find in document ──────────────────────────────────────────────────

  useEffect(() => {
    const needle = query.trim()
    if (!selected || needle.length < 2) {
      setFind(null)
      setFinding(false)
      return
    }

    const controller = new AbortController()
    setFinding(true)
    // Debounced: typing "corrosion" would otherwise run nine searches, and the
    // last one is the only one anybody wanted.
    const timer = setTimeout(() => {
      api
        .findInDocument(selected.id, needle, controller.signal)
        .then((r) => {
          setFind(r)
          setFinding(false)
          // Land on the first hit straight away. Searching and then having to
          // click a result to see anything is a step with no purpose.
          if (r.pages.length > 0) go(r.pages[0].page)
        })
        .catch((err) => {
          if (err.name !== 'AbortError') {
            setFinding(false)
            setError(err.message)
          }
        })
    }, 260)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [query, selected]) // eslint-disable-line react-hooks/exhaustive-deps

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
        if (cancelled) return

        // The highlight is drawn from the PDF's OWN text, not from the index
        // that produced the hit list. Keeping the two independent is the point:
        // a page listed as a hit with nothing marked on it means the parser and
        // the page disagree, and that is worth being able to see.
        const needle = query.trim()
        setOnPage(
          needle.length >= 2
            ? await paintMatches(rendered, canvas, viewport, ratio, needle)
            : null
        )

        scrollRef.current?.scrollTo({ top: 0 })
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
  }, [pdf, page, zoom, query])

  function go(next) {
    if (!pdf) return
    const clamped = clamp(next, 1, pdf.numPages)
    setPage(clamped)
    setPageDraft(String(clamped))
  }

  const hits = find?.pages ?? []
  const hitIndex = hits.findIndex((h) => h.page === page)

  function stepHit(delta) {
    if (hits.length === 0) return
    // From a page that is not itself a hit, step to the nearest one in that
    // direction rather than doing nothing.
    let next
    if (hitIndex >= 0) {
      next = (hitIndex + delta + hits.length) % hits.length
    } else {
      next = delta > 0
        ? hits.findIndex((h) => h.page > page)
        : findLastIndex(hits, (h) => h.page < page)
      if (next < 0) next = delta > 0 ? 0 : hits.length - 1
    }
    go(hits[next].page)
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
                <div className="docs-find">
                  <IconSearch width={13} height={13} />
                  <input
                    type="text"
                    value={query}
                    placeholder="Find in document"
                    spellCheck="false"
                    aria-label="Find in document"
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        stepHit(e.shiftKey ? -1 : 1)
                      }
                      if (e.key === 'Escape') setQuery('')
                    }}
                  />

                  {query.trim().length >= 2 && (
                    <span className="docs-find-count eyebrow">
                      {finding
                        ? 'Searching'
                        : hits.length === 0
                          ? 'No pages'
                          : `${hitIndex >= 0 ? hitIndex + 1 : '–'} / ${find.total_pages} pages`}
                    </span>
                  )}

                  {hits.length > 0 && (
                    <>
                      <button
                        className="docs-step docs-step--sm"
                        onClick={() => stepHit(-1)}
                        aria-label="Previous page with a match"
                      >
                        <IconChevron width={11} height={11} className="rot-180" />
                      </button>
                      <button
                        className="docs-step docs-step--sm"
                        onClick={() => stepHit(1)}
                        aria-label="Next page with a match"
                      >
                        <IconChevron width={11} height={11} />
                      </button>
                    </>
                  )}
                </div>
              )}

              {pdf && (
                <div className="docs-nav">
                  <button
                    className="docs-step"
                    onClick={() => go(page - 1)}
                    disabled={page <= 1}
                    aria-label="Previous page"
                  >
                    <IconChevron width={13} height={13} className="rot-180" />
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
                    <IconChevron width={13} height={13} />
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

            {/* A passage is chunked from where it starts, so a hit page can be
                the page the passage BEGINS on while the phrase itself falls
                just over the break. Saying so beats leaving an unexplained
                page with nothing marked on it. */}
            {onPage === 0 && hitIndex >= 0 && (
              <p className="docs-note">
                Nothing marked on this page — the passage starts here and the
                phrase falls after the break. Try page {page + 1}.
              </p>
            )}

            {hits.length > 0 && (
              <ul className="docs-hits">
                {hits.map((h) => (
                  <li key={h.page}>
                    <button
                      className={`docs-hit ${h.page === page ? 'is-current' : ''}`}
                      onClick={() => go(h.page)}
                    >
                      <span className="docs-hit-page eyebrow">p. {h.page}</span>
                      {h.section && <span className="docs-hit-sec">{h.section}</span>}
                      <span className="docs-hit-text">{h.snippet}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}

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

function findLastIndex(list, predicate) {
  for (let i = list.length - 1; i >= 0; i -= 1) if (predicate(list[i])) return i
  return -1
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value))
}

/**
 * Mark every occurrence of `needle` on a rendered page. Returns the count.
 *
 * pdf.js emits text as runs, and a run boundary falls wherever the typesetting
 * changed — mid-phrase, mid-word, at every line break. Searching each run on
 * its own therefore misses most real phrases: "corrosion addition" appears on
 * page 116 of the rulebook and matches no single run. So the runs are joined,
 * the search happens on the joined text, and each match is mapped back to the
 * runs it covers — one rectangle per run it crosses.
 *
 * Whitespace in the query matches any run of whitespace, so a phrase broken
 * across a line still matches.
 *
 * Placement within a run is by character proportion, since pdf.js gives a run
 * a width but not per-character positions. That is approximate by construction
 * and can sit a glyph wide in proportional type. It is a highlight, not a
 * selection: its job is to draw the eye to the right line.
 */
async function paintMatches(page, canvas, viewport, ratio, needle) {
  const content = await page.getTextContent()
  const items = content.items.filter((i) => i.str)

  // Joined page text, plus a character-to-run map to find the way back.
  let joined = ''
  const owner = []
  for (const item of items) {
    for (let i = 0; i < item.str.length; i += 1) owner.push({ item, i })
    joined += item.str
    if (item.hasEOL) {
      joined += ' '
      owner.push(null) // the separator belongs to no run
    }
  }

  const pattern = new RegExp(
    needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+'),
    'gi'
  )

  const context = canvas.getContext('2d')
  context.save()
  context.scale(ratio, ratio)
  context.fillStyle = 'rgba(53, 198, 224, 0.34)'

  let count = 0
  for (const match of joined.matchAll(pattern)) {
    count += 1

    // Group the matched characters by the run they came from: a phrase
    // crossing a run boundary gets a rectangle on each side.
    const segments = new Map()
    for (let at = match.index; at < match.index + match[0].length; at += 1) {
      const slot = owner[at]
      if (!slot) continue
      const span = segments.get(slot.item)
      if (span) span[1] = slot.i
      else segments.set(slot.item, [slot.i, slot.i])
    }

    for (const [item, [from, to]] of segments) {
      const [a, b, c, d, e, f] = pdfjs.Util.transform(viewport.transform, item.transform)
      const height = Math.hypot(c, d) || Math.hypot(a, b)
      const width = item.width * viewport.scale
      const per = width / item.str.length

      context.fillRect(e + from * per, f - height, (to - from + 1) * per, height * 1.16)
    }
  }

  context.restore()
  return count
}
