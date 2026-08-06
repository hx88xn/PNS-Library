import { useCallback, useEffect, useRef, useState } from 'react'
import { IconSearch, IconClose, IconDoc } from '../components/Icons.jsx'
import { highlight } from '../lib/search.js'
import * as api from '../lib/api.js'

const PAGE_SIZE = 50
const DEBOUNCE_MS = 250

function Marked({ text, terms }) {
  if (!terms || terms.length === 0) return text
  return highlight(text, terms).map((run, i) =>
    run.hit ? <mark key={i}>{run.text}</mark> : <span key={i}>{run.text}</span>
  )
}

export default function Retriever({ collection, setCollection, collections }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(() => new Set())
  const [corpusMatches, setCorpusMatches] = useState(null)
  const [occurrences, setOccurrences] = useState(null)
  // 'ranked' = best matches first; 'all' = every chunk containing the terms,
  // which is what you need when checking a document was ingested completely.
  const [mode, setMode] = useState('ranked')

  const abortRef = useRef(null)

  const load = useCallback(async (q, coll, searchMode) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError('')

    try {
      if (q.trim()) {
        const data = await api.search(
          { q: q.trim(), collection: coll, limit: PAGE_SIZE, mode: searchMode },
          controller.signal
        )
        setCorpusMatches(data.corpus_matches)
        setOccurrences(data.occurrences)
        setResults(
          data.results.map((hit) => ({
            chunk: hit.chunk,
            relevance: hit.relevance,
            matchedTerms: hit.matched_terms
          }))
        )
        setTotal(data.total)
      } else {
        // Empty box lists the whole index, which is what the tab is for.
        const data = await api.listChunks({ limit: PAGE_SIZE, collection: coll }, controller.signal)
        setResults(data.results.map((chunk) => ({ chunk, relevance: 0, matchedTerms: [] })))
        setTotal(data.total)
        setCorpusMatches(null)
        setOccurrences(null)
      }
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message)
      setResults([])
      setTotal(0)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }, [])

  // Debounce the query; a collection change applies at once.
  useEffect(() => {
    const timer = setTimeout(() => load(query, collection, mode), query ? DEBOUNCE_MS : 0)
    return () => clearTimeout(timer)
  }, [query, collection, mode, load])

  // A new query starts ranked; "show all" is a deliberate step from there.
  useEffect(() => setMode('ranked'), [query])

  useEffect(() => () => abortRef.current?.abort(), [])

  function toggle(id) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const searching = query.trim().length > 0
  const collectionLabel =
    collection === 'all'
      ? 'All documents'
      : collections.find((c) => c.id === collection)?.label ?? collection

  return (
    <div className="retriever">
      <div className="retriever-head">
        <div className="searchbar">
          <IconSearch width={17} height={17} className="searchbar-icon" />
          <input
            type="search"
            className="searchbar-input"
            value={query}
            spellCheck="false"
            placeholder="Search the indexed corpus — try “damage stability” or “A-60”"
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search chunks"
          />
          {searching && (
            <button
              className="searchbar-clear"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              title="Clear"
            >
              <IconClose width={15} height={15} />
            </button>
          )}
        </div>

        <div className="retriever-status">
          <p className="retriever-count">
            {loading ? (
              <span className="retriever-loading">Searching the index…</span>
            ) : searching ? (
              <>
                <strong>{total}</strong>{' '}
                {mode === 'all' ? 'chunks contain' : 'best matches for'}{' '}
                <span className="q">“{query.trim()}”</span>
                {mode === 'ranked' && corpusMatches != null && corpusMatches > total && (
                  <>
                    {' · '}
                    <button className="show-all" onClick={() => setMode('all')}>
                      show all {corpusMatches}
                    </button>
                  </>
                )}
                {mode === 'all' && (
                  <>
                    {' · '}
                    <button className="show-all" onClick={() => setMode('ranked')}>
                      rank by relevance
                    </button>
                  </>
                )}
              </>
            ) : (
              <>
                <strong>{total}</strong> {total === 1 ? 'chunk' : 'chunks'} in the index
              </>
            )}
          </p>
          {searching && occurrences != null && (
            <span
              className="occurrences eyebrow"
              title="Counted in the source documents, not the chunks — chunks overlap, so counting across them would overstate it"
            >
              {occurrences} in source
            </span>
          )}
          <span className="retriever-scope eyebrow">{collectionLabel}</span>
          {collection !== 'all' && (
            <button className="scope-clear eyebrow" onClick={() => setCollection('all')}>
              Clear filter
            </button>
          )}
        </div>
      </div>

      <div className="retriever-scroll">
        {error ? (
          <div className="retriever-empty">
            <p className="retriever-empty-title">Cannot reach the library</p>
            <p className="retriever-empty-sub">{error}</p>
            <button className="btn-ghost" onClick={() => load(query, collection, mode)}>
              Try again
            </button>
          </div>
        ) : results.length === 0 && !loading ? (
          <div className="retriever-empty">
            <p className="retriever-empty-title">
              {searching ? `No chunk matches “${query.trim()}”` : 'The index is empty'}
            </p>
            <p className="retriever-empty-sub">
              {searching ? (
                <>
                  Search the terms the documents use — <em>metacentric height</em>,{' '}
                  <em>section modulus</em>, <em>cavitation</em>, <em>A-60</em> — or clear the
                  search to browse the whole index.
                </>
              ) : (
                <>
                  No documents have been ingested yet. On the server, run{' '}
                  <em>pdas ingest &lt;path&gt;</em>.
                </>
              )}
            </p>
            {searching && (
              <button className="btn-ghost" onClick={() => setQuery('')}>
                Show all chunks
              </button>
            )}
          </div>
        ) : (
          <ul className="chunk-list">
            {results.map(({ chunk, relevance, matchedTerms }) => {
              const isOpen = expanded.has(chunk.id)
              return (
                <li key={chunk.id}>
                  <article className={`chunk ${isOpen ? 'is-open' : ''}`}>
                    <header className="chunk-head">
                      <div className="chunk-ref">
                        <IconDoc width={14} height={14} />
                        <span className="chunk-doc">
                          <Marked text={chunk.doc} terms={matchedTerms} />
                        </span>
                        <span className="chunk-id eyebrow">{chunk.id}</span>
                      </div>
                      {searching && (
                        <div
                          className="relevance"
                          title={`Relevance ${Math.round(relevance * 100)}%`}
                        >
                          <span className="relevance-bar">
                            <span style={{ width: `${Math.max(6, relevance * 100)}%` }} />
                          </span>
                          <span className="relevance-num eyebrow">
                            {Math.round(relevance * 100)}
                          </span>
                        </div>
                      )}
                    </header>

                    <h3 className="chunk-title">
                      <Marked text={chunk.title} terms={matchedTerms} />
                    </h3>

                    <p className={`chunk-text ${isOpen ? '' : 'is-clamped'}`}>
                      <Marked text={chunk.text} terms={matchedTerms} />
                    </p>

                    <button className="chunk-more" onClick={() => toggle(chunk.id)}>
                      {isOpen ? 'Show less' : 'Show full passage'}
                    </button>

                    <footer className="chunk-foot">
                      {chunk.section && (
                        <>
                          <span className="chunk-meta">
                            <Marked text={chunk.section} terms={matchedTerms} />
                          </span>
                          <span className="chunk-dot" aria-hidden="true" />
                        </>
                      )}
                      {chunk.page != null && (
                        <>
                          <span className="chunk-meta eyebrow">p. {chunk.page}</span>
                          <span className="chunk-dot" aria-hidden="true" />
                        </>
                      )}
                      {chunk.revision && (
                        <span className="chunk-meta eyebrow">{chunk.revision}</span>
                      )}
                      <span
                        className={`chunk-class eyebrow ${
                          chunk.classification === 'RESTRICTED' ? 'is-restricted' : ''
                        }`}
                      >
                        {chunk.classification}
                      </span>
                      <ul className="chunk-tags">
                        {chunk.tags.map((t) => (
                          <li key={t}>
                            <button className="tag" onClick={() => setQuery(t)} title={`Search “${t}”`}>
                              {t}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </footer>
                  </article>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
  )
}
