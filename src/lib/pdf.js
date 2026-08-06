/**
 * pdf.js, wired for an air-gapped build.
 *
 * Every asset pdf.js can fetch at runtime is resolved locally. The library's
 * defaults point at a CDN — on the server those are requests that never
 * complete, producing a viewer that renders the wrong glyphs or nothing, with
 * nothing in the interface to say why.
 *
 *   - the worker goes through Vite, so it lands in the bundle
 *   - fonts and character maps are copied into public/pdfjs at build time
 *     (scripts/copy-pdfjs-assets.mjs) and addressed relative to the document,
 *     which holds for both the dev server and file:// in the packaged app
 */
import * as pdfjs from 'pdfjs-dist/build/pdf.mjs'
import workerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const ASSETS = new URL('pdfjs/', document.baseURI).href

export { pdfjs }

/**
 * Open a PDF from bytes.
 *
 * Returns the **loading task**, not the document promise. The document proxy
 * has no `destroy()` in pdf.js 6 — only the loading task does — and closing a
 * fifteen-hundred-page book properly matters here: each open one holds a
 * worker and its decoded page cache.
 *
 * Takes ownership of the buffer: pdf.js transfers it to the worker, after
 * which the caller's view of it is detached. Callers pass a fresh copy.
 */
export function openDocument(data) {
  return pdfjs.getDocument({
    data,
    standardFontDataUrl: `${ASSETS}standard_fonts/`,
    cMapUrl: `${ASSETS}cmaps/`,
    cMapPacked: true,
    isEvalSupported: false
  })
}
