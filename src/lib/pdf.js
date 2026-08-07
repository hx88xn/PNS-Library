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
// The LEGACY build, deliberately.
//
// pdf.js 6's modern build calls `Uint8Array.prototype.toHex` when it
// fingerprints a document. That method shipped in Chrome 140; Electron 33
// carries Chromium 130, so every document died on open with
// "hashOriginal.toHex is not a function" and a blank page. The legacy build
// feature-detects and polyfills it. Bundling it is a far smaller change than
// moving every client PC to a new Electron, and this app's floor is whatever
// Electron the offline installer ships.
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const ASSETS = new URL('pdfjs/', document.baseURI).href

export { pdfjs }

/**
 * Open a PDF, fetched by pdf.js a range at a time.
 *
 * Returns the **loading task**, not the document promise. The document proxy
 * has no `destroy()` in pdf.js 6 — only the loading task does — and closing a
 * fifteen-hundred-page book properly matters here: each open one holds a
 * worker and its decoded page cache.
 *
 * Given the URL rather than the bytes, deliberately. The obvious reading of
 * "the corpus is RESTRICTED so the client must fetch it" is that pdf.js has to
 * be handed a buffer — true of an <iframe src>, which cannot carry a bearer
 * token, but not of pdf.js, which sends `httpHeaders` on every request it
 * makes. Handed a URL it reads the trailer and cross-reference table, then
 * asks for the pages someone actually looks at. The merged Türk Loydu rules
 * are 35 MB and 1,588 pages; downloading all of it to show page one is most of
 * the wait before the first page appears.
 *
 * disableAutoFetch is what makes that real. Without it pdf.js streams the
 * remainder in the background once the document opens, so the whole file still
 * crosses the wire and the only thing saved is the order it arrives in.
 *
 * Falls back by itself: if anything between here and the server refuses a
 * Range request, pdf.js fetches the file whole — which is exactly the old
 * behaviour, not a failure.
 */
export function openDocument({ url, headers }) {
  return pdfjs.getDocument({
    url,
    httpHeaders: headers,
    disableAutoFetch: true,
    disableStream: false,
    rangeChunkSize: 262144,
    standardFontDataUrl: `${ASSETS}standard_fonts/`,
    cMapUrl: `${ASSETS}cmaps/`,
    cMapPacked: true,
    isEvalSupported: false
  })
}
