import { useMemo } from 'react'

/**
 * A body plan — the view a ship design office draws first.
 *
 * Every curve on this sheet comes out of one table of offsets: the half-breadth
 * y at a station, at a height z above the baseline. The origin is where the
 * centreline crosses the baseline, and a station is drawn by walking that table
 * upwards from its own keel height. Nothing is placed by hand, which is what
 * keeps the sections fair and makes them converge on the origin the way they do
 * on a real sheet.
 *
 * Forebody to starboard of the centreline, afterbody to port, as the plan is
 * laid down on the loft floor. The form is a fast warship's: a fine hollow
 * entrance with pronounced flare, rise of floor forward, a hard bilge and flat
 * of bottom amidships, and a cutup running aft to a tapered transom.
 */

const W = 620
const H = 360
const CL = W / 2 // centreline
const BASE = 330 // baseline, through the keel
const D = 252 // moulded depth at midships
const MAX_B = 190 // maximum half-breadth

const STATIONS = 21 // 0 = forward perpendicular, 20 = after perpendicular
const PM = 0.55 // midships, as a fraction of the length between perpendiculars
const DWL = 0.54 // design waterline, as a fraction of moulded depth

const WATERLINES = 8
const BUTTOCKS = 6
const GRID_PAD = 24 // how far the grid runs outboard of the maximum breadth

const GX = MAX_B + GRID_PAD
const X1 = CL - GX
const X2 = CL + GX
const WATER_Y = BASE - D * DWL

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v)

// 0 → 0, 1 → 1, and flat where it arrives. Both bodies are built on it so that
// they meet at midships without a corner in any of the curves below.
const q90 = (t) => Math.sin((Math.PI / 2) * clamp01(t))

// ── The longitudinal curves ─────────────────────────────────────────────
// Everything a station needs is read off these four at its own p.

function halfBreadth(p) {
  if (p <= PM) return MAX_B * Math.pow(q90(p / PM), 1.35)
  return MAX_B * (1 - 0.45 * Math.pow(q90((p - PM) / (1 - PM)), 1.8))
}

/** Sheer: the deck sweeps up towards both ends, much further forward than aft. */
function deckHeight(p) {
  if (p <= PM) return D + 0.215 * D * Math.pow(1 - q90(p / PM), 1.45)
  return D + 0.095 * D * Math.pow(q90((p - PM) / (1 - PM)), 1.9)
}

/** Where the keel leaves the baseline: rise of floor forward, cutup aft. */
function keelHeight(p) {
  const forefoot = clamp01((0.46 - p) / 0.46)
  const cutup = clamp01((p - 0.6) / 0.4)
  return 0.46 * D * Math.pow(forefoot, 2.6) + 0.3 * D * Math.pow(cutup, 2.1)
}

/** Flare forward, a touch of tumblehome aft. Applied above the waterline only. */
function flare(p) {
  if (p <= PM) return 0.3 * Math.pow(1 - q90(p / PM), 1.3) + 0.012
  return -0.04 * Math.pow(q90((p - PM) / (1 - PM)), 1.5)
}

/**
 * How full the section is, as the exponent of a superellipse. Below 1 the
 * section is hollow — the garboards of a fine bow; 2 is a quarter ellipse;
 * above 4 a flat of bottom and a hard bilge. Tied to breadth so that fullness
 * can never run ahead of the form it is describing.
 */
function fullness(p) {
  return 0.85 + 3.25 * Math.pow(halfBreadth(p) / MAX_B, 1.9)
}

// ── The offset table ────────────────────────────────────────────────────

// Sampled bunched towards the keel: that is where the turn of bilge lives, and
// evenly spaced heights visibly cut the corner there.
const SAMPLES = 18

function offsets(p) {
  const b = halfBreadth(p)
  const zk = keelHeight(p)
  const zd = deckHeight(p)
  const depth = zd - zk
  const n = fullness(p)
  const phi = flare(p)
  const zetaDwl = clamp01((D * DWL - zk) / depth)

  const pts = []
  for (let k = 0; k <= SAMPLES; k++) {
    const zeta = Math.pow(k / SAMPLES, 1.5)
    const body = Math.pow(1 - Math.pow(1 - zeta, n), 1 / n)
    const above = zetaDwl >= 1 ? 0 : clamp01((zeta - zetaDwl) / (1 - zetaDwl))
    pts.push([b * body + b * phi * Math.pow(above, 1.7), zk + zeta * depth])
  }
  return { pts, b, zk, zd }
}

/** Offset table coordinates to the sheet. s = +1 forebody, −1 afterbody. */
const toSvg = (s) => ([y, z]) => [CL + s * y, BASE - z]

/** A station's half-breadth at an arbitrary height, for curves that cut across. */
function offsetAt(pts, z) {
  if (z <= pts[0][1]) return pts[0][0]
  const top = pts[pts.length - 1]
  if (z >= top[1]) return top[0]
  for (let k = 1; k < pts.length; k++) {
    if (pts[k][1] >= z) {
      const t = (z - pts[k - 1][1]) / (pts[k][1] - pts[k - 1][1])
      return pts[k - 1][0] + t * (pts[k][0] - pts[k - 1][0])
    }
  }
  return top[0]
}

// ── Centripetal Catmull-Rom, as cubic Béziers ───────────────────────────
//
// Centripetal — the square root on the chord length — rather than uniform. A
// uniform spline overshoots wherever the spacing changes quickly, which put a
// visible notch in every section at exactly the turn of bilge.

function smoothPath(p) {
  if (p.length < 2) return ''
  const chord = (a, b) => Math.sqrt(Math.hypot(b[0] - a[0], b[1] - a[1])) || 1e-6
  const d = [`M ${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`]

  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[i - 1] || p[i]
    const p1 = p[i]
    const p2 = p[i + 1]
    const p3 = p[i + 2] || p2
    const d1 = chord(p0, p1)
    const d2 = chord(p1, p2)
    const d3 = chord(p2, p3)

    const c1 = [0, 1].map((a) => p1[a] + ((p2[a] - p0[a]) / (d1 + d2)) * d2 / 3)
    const c2 = [0, 1].map((a) => p2[a] - ((p3[a] - p1[a]) / (d2 + d3)) * d2 / 3)

    d.push(
      `C ${c1[0].toFixed(1)} ${c1[1].toFixed(1)}, ${c2[0].toFixed(1)} ${c2[1].toFixed(1)}, ` +
        `${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`
    )
  }
  return d.join(' ')
}

// The knuckle leaves the sheer where the quarter begins, so that the two curves
// meet instead of it starting out of nowhere, and dies out part way down the
// aftmost station — below that it would simply lie along that station's own
// curve, which reads as a doubled line rather than a knuckle.
const KNUCKLE_FROM = 14
const KNUCKLE_END = 0.68 * D

function buildPlan() {
  const sections = []
  for (let i = 0; i < STATIONS; i++) {
    const p = i / (STATIONS - 1)
    const mid = Math.abs(p - PM) < 1e-9
    for (const s of mid ? [1, -1] : p < PM ? [1] : [-1]) {
      const o = offsets(p)
      sections.push({ ...o, i, p, s, d: smoothPath(o.pts.map(toSvg(s))) })
    }
  }

  // Ordered along the ship, never by breadth: tumblehome aft moves the deck
  // edge inboard of the widest point, and sorting on it scrambles the curve.
  const along = (s) => sections.filter((x) => x.s === s).sort((a, b) => a.i - b.i)
  const sheer = (s) => smoothPath(along(s).map((x) => toSvg(s)(x.pts[x.pts.length - 1])))

  const knuckle = smoothPath(
    along(-1)
      .filter((x) => x.i >= KNUCKLE_FROM)
      .map((x) => {
        const r = (x.i - KNUCKLE_FROM) / (STATIONS - 1 - KNUCKLE_FROM)
        const z = x.zd + (KNUCKLE_END - x.zd) * Math.pow(r, 1.5)
        return toSvg(-1)([offsetAt(x.pts, z), z])
      })
  )

  return { sections, sheerFwd: sheer(1), sheerAft: sheer(-1), knuckle }
}

// Waterlines are the horizontal datum, buttocks the vertical one — the two grids
// a body plan is read against.
const WATERLINE_Y = Array.from({ length: WATERLINES }, (_, k) => BASE - (D * (k + 1)) / WATERLINES)
const BUTTOCK_X = Array.from({ length: BUTTOCKS }, (_, k) => (GX * (k + 1)) / (BUTTOCKS + 1)).flatMap(
  (x) => [CL - x, CL + x]
)

/**
 * A sine, sampled as a polyline, for the water surface.
 *
 * Drawn one wavelength wider than it needs to be at each end so that
 * translating it by exactly one wavelength lands on an identical picture —
 * that is what makes the loop seamless rather than jumping at the repeat.
 */
function wave(amplitude, wavelength, offsetY = 0) {
  const points = []
  for (let x = X1 - wavelength; x <= X2 + wavelength; x += 6) {
    const y = WATER_Y + offsetY + amplitude * Math.sin((2 * Math.PI * x) / wavelength)
    points.push(`${x.toFixed(1)} ${y.toFixed(2)}`)
  }
  return `M ${points.join(' L ')}`
}

// Two, at different wavelengths and speeds. One alone reads as a drawn squiggle;
// two sliding past each other at different rates read as moving water.
const WAVE_A = { d: wave(2.4, 124) }
const WAVE_B = { d: wave(1.5, 186, 3.5) }

export default function HullLines({ variant = 'hero', className = '' }) {
  const { sections, sheerFwd, sheerAft, knuckle } = useMemo(buildPlan, [])

  const animated = variant === 'hero'
  // The ghost sits at half opacity behind the chat heading, where the full grid
  // and the knuckle only add noise. It keeps the stations and the waterlines.
  const detailed = variant === 'hero'
  // Per variant rather than per instance: two hero plans on one page would
  // share a clip path, which is harmless, and an id that changed between
  // renders would not be.
  const clipId = `hl-water-${variant}`

  return (
    <svg
      className={`hull-lines hull-lines--${variant} ${className}`}
      viewBox={`0 0 ${W} ${H}`}
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={X1} y={0} width={X2 - X1} height={H} />
        </clipPath>
      </defs>

      {/* The grid the sections are read against */}
      <g className="hl-grid">
        {WATERLINE_Y.map((y) => (
          <line key={`wl${y}`} x1={X1} x2={X2} y1={y} y2={y} />
        ))}
        <line x1={X1} x2={X2} y1={BASE} y2={BASE} />
        {detailed &&
          BUTTOCK_X.map((x) => <line key={`b${x}`} x1={x} x2={x} y1={BASE - D} y2={BASE} />)}
      </g>

      {/* Design waterline — the one measurement everything else answers to */}
      <line className="hl-dwl" x1={X1} x2={X2} y1={WATER_Y} y2={WATER_Y} />

      {/* The sea, running past. Clipped to the drawing's own width so it reads
          as part of the sheet rather than something loose behind it, and drawn
          before the sections so the hull sits in the water, not on it. */}
      {animated && (
        <g className="hl-water" clipPath={`url(#${clipId})`}>
          <path className="hl-wave hl-wave--a" d={WAVE_A.d} />
          <path className="hl-wave hl-wave--b" d={WAVE_B.d} />
        </g>
      )}

      <line className="hl-centreline" x1={CL} x2={CL} y1={BASE - D - 48} y2={BASE + 18} />

      {/* Everything belonging to the ship moves together, so it heaves and
          rolls as one body. The grid, the waterline and the centreline stay
          put — they are the datum the drawing is read against, and a datum
          that moved with the hull would show no motion at all. */}
      <g className="hl-hull">
        <g className="hl-sections">
          {sections.map(({ d, i, s }) => (
            <path
              key={`${i}-${s}`}
              d={d}
              className="hl-section"
              // Normalises every dash computation to 1, so the draw-on animation
              // is exact whatever the path's real length. See hl-section in
              // login.css for why a fixed dash length could not work.
              pathLength="1"
              style={animated ? { animationDelay: `${140 + i * 58}ms` } : undefined}
            />
          ))}
        </g>

        {/* Sheer line, each side */}
        <path className="hl-deck" d={sheerFwd} pathLength="1" />
        <path className="hl-deck" d={sheerAft} pathLength="1" />

        {detailed && <path className="hl-knuckle" d={knuckle} pathLength="1" />}

        {/* Buttock marks on the baseline */}
        <g className="hl-ticks">
          {BUTTOCK_X.map((x) => (
            <line key={`t${x}`} x1={x} x2={x} y1={BASE} y2={BASE + 8} />
          ))}
        </g>
      </g>
    </svg>
  )
}
