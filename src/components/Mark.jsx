/**
 * Office mark: three nested hull sections inside a bearing ring —
 * the same geometry as the body plan, reduced to a seal.
 */
export default function Mark({ size = 44, className = '' }) {
  return (
    <svg
      className={`mark ${className}`}
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="24" cy="24" r="22.25" className="mark-ring" />
      <circle cx="24" cy="24" r="18" className="mark-ring-inner" />
      {/* Bearing ticks at the cardinal points */}
      <g className="mark-ticks">
        <line x1="24" y1="1.5" x2="24" y2="6" />
        <line x1="24" y1="42" x2="24" y2="46.5" />
        <line x1="1.5" y1="24" x2="6" y2="24" />
        <line x1="42" y1="24" x2="46.5" y2="24" />
      </g>
      <g className="mark-hull">
        <path d="M24 34 C 30.5 34, 33.5 31, 33.5 22 L 33.5 15" />
        <path d="M24 34 C 28.5 33.5, 30 30, 30 23.5 L 30 15" />
        <path d="M24 34 C 25.5 32, 26.5 28, 26.5 24 L 26.5 15" />
      </g>
      <line x1="24" y1="12" x2="24" y2="36" className="mark-cl" />
    </svg>
  )
}
