#!/usr/bin/env python
"""Generate the PDAS application icon.

Crescent and star, white on navy — the Pakistan Navy reading has to be
immediate and unambiguous, so it carries the mark alone. The ship design office
is present only in the field behind it: drawing-paper squares and a single
dashed design waterline running through the crescent, the way a waterline is
struck across a lines plan.

That detail is deliberately quiet. It rewards a look at 512 px and disappears
entirely by 32 px, leaving a silhouette that still reads at 16 px in a taskbar.

    python assets/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

S = 1024

NAVY_TOP = "#1A5490"
NAVY_MID = "#0B2C4C"
NAVY_BOTTOM = "#04121F"
WHITE = "#FFFFFF"
SONAR = "#35C6E0"

# Crescent: an outer disc with an offset inner disc punched out of it. The
# offset direction sets which way the horns point — up and to the right, as on
# the flag, with the star seated in the opening.
# Equal radii with a modest offset. Maximum thickness works out at
# R + offset - R_inner, so equal radii make the offset alone set the weight:
# 130 here, against a 300 radius, giving flag-slim horns.
#
# An inner disc smaller than the outer gives an even-width ring that reads as a
# letter C; one larger produces two overlapping lenses. Neither is a crescent.
OUTER = (470, 560, 300)      # cx, cy, r
INNER = (551, 459, 300)

# Seated so the star's furthest reach stays inside the punched disc: 155 from
# the inner centre plus a 110 radius is 265, clear of the 300 boundary where
# the white begins. Guarantees a gap at every size instead of hoping for one.
STAR = (650, 340, 110, -16)  # cx, cy, r, rotation°

WATERLINE_Y = 618


def circle_path(cx: float, cy: float, r: float) -> str:
    """A full circle as two arcs, so several can share one path element."""
    return (
        f"M {cx - r:.1f} {cy:.1f} "
        f"a {r:.1f} {r:.1f} 0 1 0 {2 * r:.1f} 0 "
        f"a {r:.1f} {r:.1f} 0 1 0 {-2 * r:.1f} 0"
    )


def star_points(cx: float, cy: float, outer: float, rotation: float = 0.0) -> str:
    """Five-pointed star. 0.382 is the golden-section ratio that gives the flag
    star its proportions; anything fatter reads as a sheriff's badge."""
    inner = outer * 0.382
    points = []
    for k in range(5):
        a_out = math.radians(-90 + rotation + k * 72)
        a_in = math.radians(-90 + rotation + 36 + k * 72)
        points.append((cx + outer * math.cos(a_out), cy + outer * math.sin(a_out)))
        points.append((cx + inner * math.cos(a_in), cy + inner * math.sin(a_in)))
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def build() -> str:
    ox, oy, orad = OUTER
    ix, iy, irad = INNER
    sx, sy, srad, srot = STAR

    grid = "\n".join(
        f'      <line x1="{v}" y1="0" x2="{v}" y2="{S}"/>\n'
        f'      <line x1="0" y1="{v}" x2="{S}" y2="{v}"/>'
        for v in range(64, S, 64)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}">
  <defs>
    <linearGradient id="field" x1="0.1" y1="0" x2="0.7" y2="1">
      <stop offset="0" stop-color="{NAVY_TOP}"/>
      <stop offset="0.5" stop-color="{NAVY_MID}"/>
      <stop offset="1" stop-color="{NAVY_BOTTOM}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.32" cy="0.26" r="0.75">
      <stop offset="0" stop-color="{SONAR}" stop-opacity="0.22"/>
      <stop offset="1" stop-color="{SONAR}" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="field-clip">
      <rect x="0" y="0" width="{S}" height="{S}" rx="230" ry="230"/>
    </clipPath>
    <filter id="lift" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="10" stdDeviation="14"
                    flood-color="{NAVY_BOTTOM}" flood-opacity="0.30"/>
    </filter>
  </defs>

  <rect x="0" y="0" width="{S}" height="{S}" rx="230" ry="230" fill="url(#field)"/>

  <g clip-path="url(#field-clip)">
    <rect x="0" y="0" width="{S}" height="{S}" fill="url(#glow)"/>

    <!-- Drawing paper -->
    <g stroke="{WHITE}" stroke-opacity="0.05" stroke-width="2">
{grid}
    </g>

    <!-- Design waterline, struck across the plan -->
    <line x1="96" y1="{WATERLINE_Y}" x2="{S - 96}" y2="{WATERLINE_Y}"
          stroke="{SONAR}" stroke-opacity="0.40" stroke-width="9"
          stroke-dasharray="54 30" stroke-linecap="round"/>

    <!-- Crescent: outer disc, inner disc punched out -->
    <path fill-rule="evenodd" fill="{WHITE}" filter="url(#lift)"
          d="{circle_path(ox, oy, orad)} {circle_path(ix, iy, irad)}"/>

    <!-- Star, seated in the opening -->
    <polygon points="{star_points(sx, sy, srad, srot)}" fill="{WHITE}" filter="url(#lift)"/>
  </g>
</svg>
"""


def main() -> None:
    out = Path(__file__).parent / "icon.svg"
    out.write_text(build())
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
