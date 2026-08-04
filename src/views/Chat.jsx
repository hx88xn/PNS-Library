import { useEffect, useRef, useState } from 'react'
import { IconSend, IconDoc } from '../components/Icons.jsx'
import HullLines from '../components/HullLines.jsx'
import * as api from '../lib/api.js'

const OPENERS = [
  'What intact stability margin applies to a 3,000 t escort?',
  'Summarise the two-compartment damage standard.',
  'What frame spacing applies in the machinery spaces?',
  'What weight and KG margins do we carry to contract design?'
]

export default function Chat({ thread, collection, onSend, onPatchLast }) {
  const [draft, setDraft] = useState('')
  const [streaming, setStreaming] = useState(false)
  const scrollRef = useRef(null)
  const inputRef = useRef(null)
  const abortRef = useRef(null)

  const messages = thread.messages

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
          {messages.length === 0 ? (
            <div className="chat-empty">
              <HullLines variant="ghost" className="chat-empty-figure" />
              <h2 className="chat-empty-title">Ask the library</h2>
              <ul className="opener-list">
                {OPENERS.map((o) => (
                  <li key={o}>
                    <button className="opener" onClick={() => send(o)}>
                      {o}
                    </button>
                  </li>
                ))}
              </ul>
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
                    <div className="sources">
                      <p className="sources-head eyebrow">Cited</p>
                      <ul>
                        {m.sources.map((s) => (
                          <li key={s.id}>
                            <span className="source">
                              <IconDoc width={14} height={14} />
                              <span className="source-doc">{s.doc}</span>
                              {s.section && <span className="source-sec">{s.section}</span>}
                              {s.page != null && <span className="source-pg eyebrow">p. {s.page}</span>}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
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
