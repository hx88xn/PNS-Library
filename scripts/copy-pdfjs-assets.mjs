/**
 * Copy pdf.js's font and character-map data into public/.
 *
 * pdf.js fetches these at render time for any document that does not embed its
 * own fonts — common in older rulebooks typeset before embedding was routine.
 * Left unbundled, the defaults point at a CDN: on an air-gapped server that is
 * a request that never resolves and a page that renders with the wrong glyphs
 * or none at all, with nothing in the interface explaining why.
 *
 * Runs before dev and before build, so the two never disagree.
 */
import { cp, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const from = join(root, 'node_modules', 'pdfjs-dist')
const to = join(root, 'public', 'pdfjs')

await mkdir(to, { recursive: true })

for (const name of ['standard_fonts', 'cmaps']) {
  await cp(join(from, name), join(to, name), { recursive: true })
}

console.log('pdf.js assets → public/pdfjs')
