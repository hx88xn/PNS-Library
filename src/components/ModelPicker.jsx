import { useCallback, useEffect, useRef, useState } from 'react'
import { IconChevron } from './Icons.jsx'
import * as api from '../lib/api.js'

/**
 * Which model is answering, and a way to change it.
 *
 * Switching is not free and is not instant: the server evicts the current
 * weights and reads the new ones off disk, tens of seconds for a cold 4B. So
 * the control commits to saying so — the menu locks, the chosen row shows what
 * is happening, and nothing reports success until the model is actually
 * resident in VRAM.
 *
 * Sizes shown are bytes on disk, which is what Ollama reports. Deliberately
 * not labelled as VRAM: a quantised model expands when loaded and the KV cache
 * sits on top, so the two differ by enough to mislead someone budgeting an
 * 8 GB card.
 */
export default function ModelPicker({ health, onChanged }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState(null)
  const [error, setError] = useState('')

  const rootRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await api.models())
    } catch (err) {
      setError(err.message)
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [])

  // Only fetched when the menu is opened. There is no reason to ask the server
  // what it has on disk on every sign-in.
  useEffect(() => {
    if (open) load()
  }, [open, load])

  // Close on an outside click or Escape — but never mid-switch, because the
  // menu is the only place the progress is shown.
  useEffect(() => {
    if (!open) return

    function onPointerDown(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    function onKey(event) {
      if (event.key === 'Escape' && !switching) setOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, switching])

  async function choose(name) {
    if (switching || name === data?.current) return

    setSwitching(name)
    setError('')
    try {
      setData(await api.selectModel(name))
      onChanged?.()
      setOpen(false)
    } catch (err) {
      setError(err.message)
      load() // say what is actually resident now, not what we hoped
    } finally {
      setSwitching(null)
    }
  }

  const unreachable = !health
  const degraded = health && health.status !== 'ok'
  const label = unreachable
    ? 'Offline'
    : switching || data?.current || health.llm_model

  return (
    <div className="picker" ref={rootRef}>
      <button
        className={`conn eyebrow ${unreachable ? 'is-down' : degraded ? 'is-warn' : ''} ${
          open ? 'is-open' : ''
        }`}
        onClick={() => setOpen((v) => !v)}
        disabled={unreachable}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={
          unreachable
            ? 'The server cannot be reached'
            : degraded
              ? health.problems?.[0]
              : `${health.chunk_count} chunks indexed · click to change model`
        }
      >
        <span className={`conn-dot ${switching ? 'is-working' : ''}`} aria-hidden="true" />
        <span className="conn-label">{label}</span>
        {!unreachable && <IconChevron width={11} height={11} className="picker-caret" />}
      </button>

      {open && (
        <div className="picker-menu" role="listbox" aria-label="Generation model">
          <p className="picker-head eyebrow">Generation model</p>

          {loading && !data ? (
            <p className="picker-note">Reading the model store…</p>
          ) : error && !data ? (
            <p className="picker-note is-error">{error}</p>
          ) : (
            <ul className="picker-list">
              {data?.available.map((m) => {
                const current = m.name === data.current
                const busy = switching === m.name
                return (
                  <li key={m.name}>
                    <button
                      className={`picker-item ${current ? 'is-current' : ''}`}
                      role="option"
                      aria-selected={current}
                      disabled={!!switching}
                      onClick={() => choose(m.name)}
                    >
                      <span className="picker-tick" aria-hidden="true">
                        {current ? '●' : ''}
                      </span>
                      <span className="picker-body">
                        <span className="picker-name">{m.name}</span>
                        <span className="picker-meta eyebrow">
                          {[m.parameter_size, m.quantization, bytes(m.size)]
                            .filter(Boolean)
                            .join(' · ')}
                        </span>
                      </span>
                      <span className="picker-state eyebrow">
                        {busy ? 'Loading' : m.loaded ? 'In VRAM' : ''}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}

          {error && data && <p className="picker-note is-error">{error}</p>}

          <p className="picker-foot">
            One model is held in VRAM at a time. Switching evicts the current
            one first, which takes a moment.
            {data?.embed_model && (
              <>
                {' '}
                Embeddings stay on <b>{data.embed_model}</b> and are not
                affected.
              </>
            )}
          </p>
        </div>
      )}
    </div>
  )
}

function bytes(n) {
  if (!n) return ''
  const gb = n / 1024 ** 3
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.round(n / 1024 ** 2)} MB`
}
