import { useMemo } from 'react'

/**
 * A body plan — the view a ship design office draws first.
 * Transverse sections at each numbered station: forward sections to
 * starboard of the centreline, aft sections to port, as the lines plan is
 * laid down on the loft floor. Sections carry flat of bottom amidships, a
 * rising forefoot at the ends, and sheer in the deck line.
 */

const W = 620
const H = 360
const CL = W / 2 // centreline
const BASE = 300 // baseline, through the keel
const D = 232 // moulded depth at midships
const MAX_B = 214 // maximum half-breadth

const STATIONS = 21 // 0 = after perpendicular, 20 = forward perpendicular

function geometry(i) {
  const u = i / (STATIONS - 1)
  const fwd = u >= 0.5
  const s = fwd ? 1 : -1

  const fullness = Math.pow(Math.sin(Math.PI * u), 1.35) // 1 amidships, 0 at the ends
  const b = MAX_B * (0.24 + 0.76 * Math.pow(Math.sin(Math.PI * u), 0.62))

  // Flat of bottom: broad amidships, gone by the time the sections go fine.
  const flat = b * 0.34 * Math.pow(fullness, 2.1)

  // The forefoot lifts off the baseline towards the perpendiculars, more
  // sharply forward where the stem is raked.
  const rise = Math.pow(1 - Math.sin(Math.PI * u), 2.3)
  const keelY = BASE - D * rise * (fwd ? 0.4 : 0.24)

  // Sheer: the deck sweeps up towards the ends, and further forward than aft.
  const sheer = D * (0.115 * Math.pow(1 - Math.sin(Math.PI * u), 1.7)) * (fwd ? 1.35 : 0.85)
  const deckY = BASE - D - sheer

  const dx = b - flat
  const dy = BASE - deckY

  // Full sections turn through a hard bilge; fine sections run out as a V.
  const t = fullness
  const c1x = flat + dx * (0.1 + 0.65 * t)
  const c1y = BASE - dy * (0.45 - 0.45 * t)
  const c2x = flat + dx * (0.55 + 0.45 * t)
  const c2y = BASE - dy * (0.88 - 0.53 * t)

  const d =
    `M ${CL} ${keelY} ` +
    `L ${CL + s * flat} ${BASE} ` +
    `C ${CL + s * c1x} ${c1y}, ${CL + s * c2x} ${c2y}, ${CL + s * b} ${deckY}`

  return { d, i, s, b, deckY, deckX: CL + s * b }
}

/** Deck edge through the outermost point of every station, each side. */
function sheerLine(points) {
  return points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.deckX} ${p.deckY}`)
    .join(' ')
}

export default function HullLines({ variant = 'hero', className = '' }) {
  const { sections, sheerFwd, sheerAft } = useMemo(() => {
    const all = Array.from({ length: STATIONS }, (_, i) => geometry(i))
    const fwd = all.filter((g) => g.s === 1).sort((a, b) => a.deckX - b.deckX)
    const aft = all.filter((g) => g.s === -1).sort((a, b) => b.deckX - a.deckX)
    return { sections: all, sheerFwd: sheerLine(fwd), sheerAft: sheerLine(aft) }
  }, [])

  const waterlines = [0.18, 0.36, 0.54, 0.72, 0.9]
  const animated = variant === 'hero'
  const x1 = CL - MAX_B - 22
  const x2 = CL + MAX_B + 22

  return (
    <svg
      className={`hull-lines hull-lines--${variant} ${className}`}
      viewBox={`0 0 ${W} ${H}`}
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid meet"
    >
      {/* Waterlines and baseline — the horizontal grid the sections are read against */}
      <g className="hl-grid">
        {waterlines.map((f) => (
          <line key={f} x1={x1} x2={x2} y1={BASE - D * f} y2={BASE - D * f} />
        ))}
        <line x1={x1} x2={x2} y1={BASE} y2={BASE} />
      </g>

      {/* Design waterline — the one measurement everything else answers to */}
      <line className="hl-dwl" x1={x1} x2={x2} y1={BASE - D * 0.54} y2={BASE - D * 0.54} />

      <line className="hl-centreline" x1={CL} x2={CL} y1={BASE - D - 40} y2={BASE + 18} />

      <g className="hl-sections">
        {sections.map(({ d, i }) => (
          <path
            key={i}
            d={d}
            className="hl-section"
            style={animated ? { animationDelay: `${140 + i * 58}ms` } : undefined}
          />
        ))}
      </g>

      {/* Sheer line, each side */}
      <path className="hl-deck" d={sheerFwd} />
      <path className="hl-deck" d={sheerAft} />

      {/* Station ticks on the baseline */}
      <g className="hl-ticks">
        {sections.map(({ i, b, s }) => (
          <line key={i} x1={CL + s * b} x2={CL + s * b} y1={BASE} y2={BASE + 8} />
        ))}
      </g>
    </svg>
  )
}
