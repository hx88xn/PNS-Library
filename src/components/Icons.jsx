const base = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true
}

export const IconChat = (p) => (
  <svg {...base} {...p}>
    <path d="M21 12a8 8 0 0 1-8 8H7l-4 3v-6.5A8 8 0 0 1 11 4h2a8 8 0 0 1 8 8Z" />
    <path d="M8.5 11h7M8.5 14.5h4" />
  </svg>
)

export const IconRetriever = (p) => (
  <svg {...base} {...p}>
    <rect x="3" y="3.5" width="18" height="5" rx="1.2" />
    <rect x="3" y="12" width="9" height="5" rx="1.2" />
    <circle cx="17" cy="16" r="3.4" />
    <path d="m19.6 18.6 2.2 2.2" />
  </svg>
)

export const IconChevron = (p) => (
  <svg {...base} {...p}>
    <path d="m9 6 6 6-6 6" />
  </svg>
)

export const IconPlus = (p) => (
  <svg {...base} {...p}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)

export const IconSearch = (p) => (
  <svg {...base} {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" />
  </svg>
)

export const IconSend = (p) => (
  <svg {...base} {...p}>
    <path d="M4.5 12 20 4.5 12.5 20l-2-6.5-6-1.5Z" />
  </svg>
)

export const IconClose = (p) => (
  <svg {...base} {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
)

export const IconPanel = (p) => (
  <svg {...base} {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9.5 4v16" />
  </svg>
)

export const IconSignOut = (p) => (
  <svg {...base} {...p}>
    <path d="M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4" />
    <path d="M10 8 6 12l4 4M6 12h9" />
  </svg>
)

export const IconDoc = (p) => (
  <svg {...base} {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
    <path d="M14 3v5h5M9 13h6M9 16.5h4" />
  </svg>
)

export const IconCopy = (p) => (
  <svg {...base} {...p}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a2 2 0 0 1 2-2h9" />
  </svg>
)

export const IconMinimize = (p) => (
  <svg {...base} {...p}>
    <path d="M5 12h14" />
  </svg>
)

export const IconMaximize = (p) => (
  <svg {...base} {...p}>
    <rect x="5" y="5" width="14" height="14" rx="1.5" />
  </svg>
)

export const IconIngest = (p) => (
  <svg {...base} {...p}>
    <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    <path d="M12 16V4" />
    <path d="m7.5 8.5 4.5-4.5 4.5 4.5" />
  </svg>
)

/** Documents: a shelf of bound volumes, distinct from the single sheet of IconDoc. */
export const IconLibrary = (p) => (
  <svg {...base} {...p}>
    <path d="M4 4v16" />
    <path d="M8 4v16" />
    <path d="M12 4v16" />
    <path d="m16.5 4.8 3.6 15.1" />
    <path d="M3 20h18" />
  </svg>
)
