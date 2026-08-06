import { useEffect, useRef, useState } from 'react'
import { IconSend, IconDoc, IconChevron } from '../components/Icons.jsx'
import HullLines from '../components/HullLines.jsx'
import * as api from '../lib/api.js'

export default function Chat({ thread, collection, onSend, onPatchLast, onOpenCitation }) {
  const [draft, setDraft] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [openers, setOpeners] = useState(null)
  const scrollRef = useRef(null)
  const inputRef = useRef(null)
  const abortRef = useRef(null)

  const messages = thread.messages
  const empty = messages.length === 0

  // Openers come from the corpus, so they are fetched, not written here. Only
  // when the screen is actually empty: on a cold index this waits on the model,
  // and there is no reason to spend that on a thread already in progress.
  useEffect(() => {
    if (!empty) return
    const controller = new AbortController()
    setOpeners(null)
    api
      .suggestions(collection, controller.signal)
      .then((r) => setOpeners(r.suggestions.slice(0, 4)))
      .catch(() => setOpeners([]))
    return () => controller.abort()
  }, [empty, collection])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, streaming])

  useEffect(() => () => abortRef.current?.abort(), [])

  async function send(text) {
    const question = text.trim()
    if (!question || streaming) return

    setDraft('')
    setStreaming(true)

    // History before this turn, so the server sees the same conversation.
    const history = messages.map((m) => ({ role: m.role, content: m.text }))

    onSend({ role: 'user', text: question })
    onSend({ role: 'assistant', text: '', sources: [], pending: true })

    const controller = new AbortController()
    abortRef.current = controller

    let answer = ''
    try {
      await api.chatStream(
        { message: question, collection, history },
        {
          signal: controller.signal,
          onToken: (token) => {
            answer += token
            onPatchLast({ text: answer, pending: false })
          },
          onCitations: (citations) => onPatchLast({ sources: citations, pending: false })
        }
      )
    } catch (err) {
      if (err.name !== 'AbortError') {
        onPatchLast({ text: answer || err.message, error: !answer, pending: false })
      }
    } finally {
      setStreaming(false)
      inputRef.current?.focus()
    }
  }

  function onKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send(draft)
    }
  }

  return (
    <div className="chat">
      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-inner">
          {empty ? (
            <div className="chat-empty">
              <HullLines variant="ghost" className="chat-empty-figure" />
              <h2 className="chat-empty-title">Ask the library</h2>

              {openers === null ? (
                // Placeholders, not a spinner: the openers land in this exact
                // shape, so nothing below them jumps when they arrive.
                <ul className="opener-list" aria-hidden="true">
                  {[0, 1, 2, 3].map((i) => (
                    <li key={i}>
                      <span className="opener opener--waiting" />
                    </li>
                  ))}
                </ul>
              ) : openers.length > 0 ? (
                <ul className="opener-list">
                  {openers.map((o) => (
                    <li key={o}>
                      <button className="opener" onClick={() => send(o)}>
                        {o}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="chat-empty-note">
                  Ingest a document to see suggested questions here.
                </p>
              )}
            </div>
          ) : (
            messages.map((m, i) => (
              <article key={i} className={`msg msg--${m.role}`}>
                <div className="msg-gutter">
                  <span className="msg-who eyebrow">{m.role === 'user' ? 'You' : 'PDAS'}</span>
                </div>
                <div className="msg-body">
                  {m.pending && !m.text ? (
                    <div className="msg-bubble msg-bubble--thinking">
                      <span className="sounding" aria-label="Searching the index">
                        <i />
                        <i />
                        <i />
                      </span>
                      <span className="thinking-label">Searching the index</span>
                    </div>
                  ) : (
                    <div className={`msg-bubble ${m.error ? 'is-error' : ''}`}>
                      {m.text.split('\n\n').map((para, j) => (
                        <p key={j}>{para}</p>
                      ))}
                    </div>
                  )}

                  {m.sources?.length > 0 && (
                    <details className="sources">
                      <summary className="sources-head">
                        <IconChevron width={12} height={12} className="sources-chevron" />
                        <span className="eyebrow">Cited</span>
                        <span className="sources-count eyebrow">{m.sources.length}</span>
                      </summary>
                      <ul>
                        {m.sources.map((s) => {
                          // A citation without a document_id predates source
                          // files being kept, so there is nothing to open. It
                          // stays readable, it just isn't a button.
                          const openable = s.document_id != null
                          const Tag = openable ? 'button' : 'span'
                          return (
                            <li key={s.id}>
                              <Tag
                                className={`source ${openable ? 'is-openable' : ''}`}
                                {...(openable
                                  ? {
                                      onClick: () => onOpenCitation?.(s),
                                      title: `Open ${s.doc}${s.page != null ? ` at page ${s.page}` : ''}`
                                    }
                                  : {})}
                              >
                                <IconDoc width={14} height={14} />
                                <span className="source-doc">{s.doc}</span>
                                {s.section && <span className="source-sec">{s.section}</span>}
                                {s.page != null && (
                                  <span className="source-pg eyebrow">p. {s.page}</span>
                                )}
                              </Tag>
                            </li>
                          )
                        })}
                      </ul>
                    </details>
                  )}
                </div>
              </article>
            ))
          )}
        </div>
      </div>

      <div className="composer">
        <div className="composer-inner">
          <textarea
            ref={inputRef}
            className="composer-input"
            rows={1}
            value={draft}
            placeholder="Ask about stability, scantlings, propulsion, signatures…"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            className="composer-send"
            onClick={() => send(draft)}
            disabled={!draft.trim() || streaming}
            aria-label="Send"
            title="Send"
          >
            <IconSend width={17} height={17} />
          </button>
        </div>
        <p className="composer-hint eyebrow">
          Enter to send · Shift + Enter for a new line · Check every figure against the source sheet
        </p>
      </div>
    </div>
  )
}
