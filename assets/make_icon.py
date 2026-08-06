#!/usr/bin/env python
"""Generate the PDAS application icon.

The office mark: nested hull sections inside a bearing ring. The sections are
the transverse cuts a design office draws first; the ring and its cardinal
ticks are the compass rose those sections are oriented against. Same device as
the title bar and the sign-in screen, so the icon in the taskbar and the mark
in the application are recognisably one thing.

Cyan on navy, and no lettering — at 16 px a glyph turns to mud, while a ring
with something inside it still reads.

    python assets/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

S = 1024
C = S / 2  # centre

NAVY_TOP = "#1A5490"
NAVY_MID = "#0B2C4C"
NAVY_BOTTOM = "#04121F"
SONAR = "#35C6E0"
PALE = "#8FD9EA"

R_OUTER = 330
R_INNER = 268

# Hull sections, scaled from the 48-unit Mark component. Keel on the
# centreline, each section fuller than the last, ending at the deck line.
KEEL_Y = 661
DECK_Y = 378
SECTIONS = [
    (654, "M {c} {k} C 609 {k}, 654 616, 654 482 L 654 {d}"),
    (601, "M {c} {k} C 579 653, 601 601, 601 505 L 601 {d}"),
    (549, "M {c} {k} C 534 631, 549 572, 549 512 L 549 {d}"),
]


def build() -> str:
    sections = "\n".join(
        f'      <path d="{tmpl.format(c=int(C), k=KEEL_Y, d=DECK_Y)}" />'
        for _, tmpl in SECTIONS
    )

    grid = "\n".join(
        f'      <line x1="{v}" y1="0" x2="{v}" y2="{S}"/>\n'
        f'      <line x1="0" y1="{v}" x2="{S}" y2="{v}"/>'
        for v in range(64, S, 64)
    )

    # Cardinal ticks, crossing the outer ring the way bearing marks do.
    ticks = "\n".join(
        f'      <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>'
        for x1, y1, x2, y2 in [
            (C, C - 350, C, C - 262),   # N
            (C, C + 262, C, C + 350),   # S
            (C - 350, C, C - 262, C),   # W
            (C + 262, C, C + 350, C),   # E
        ]
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
  <defs>
    <linearGradient id="field" x1="0.1" y1="0" x2="0.7" y2="1">
      <stop offset="0" stop-color="{NAVY_TOP}"/>
      <stop offset="0.5" stop-color="{NAVY_MID}"/>
      <stop offset="1" stop-color="{NAVY_BOTTOM}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.5" cy="0.42" r="0.6">
      <stop offset="0" stop-color="{SONAR}" stop-opacity="0.20"/>
      <stop offset="1" stop-color="{SONAR}" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="field-clip">
      <rect x="0" y="0" width="{S}" height="{S}" rx="230" ry="230"/>
    </clipPath>
  </defs>

  <rect x="0" y="0" width="{S}" height="{S}" rx="230" ry="230" fill="url(#field)"/>

  <g clip-path="url(#field-clip)" fill="none" stroke-linecap="round">
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#glow)"/>

    <!-- Drawing paper -->
    <g stroke="#FFFFFF" stroke-opacity="0.05" stroke-width="2">
{grid}
    </g>

    <!-- Bearing ring -->
    <circle cx="{C}" cy="{C}" r="{R_OUTER}" stroke="{SONAR}" stroke-opacity="0.5" stroke-width="13"/>
    <circle cx="{C}" cy="{C}" r="{R_INNER}" stroke="{SONAR}" stroke-opacity="0.22" stroke-width="9"/>

    <g stroke="{SONAR}" stroke-opacity="0.75" stroke-width="15">
{ticks}
    </g>

    <!-- Centreline, struck through the keel -->
    <line x1="{C}" y1="333" x2="{C}" y2="691"
          stroke="{SONAR}" stroke-opacity="0.45" stroke-width="9"
          stroke-dasharray="26 18"/>

    <!-- The sections themselves -->
    <g stroke="{PALE}" stroke-width="21" stroke-linejoin="round">
{sections}
    </g>
  </g>
</svg>
"""


def main() -> None:
    out = Path(__file__).parent / "icon.svg"
    out.write_text(build())
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
