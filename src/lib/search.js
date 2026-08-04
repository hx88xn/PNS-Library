/**
 * Match highlighting.
 *
 * Ranking moved to the server (hybrid dense + BM25); the client only marks up
 * the terms the server reports as genuinely present in each chunk.
 */

/** Split text into [{ text, hit }] runs so matched terms can be marked up. */
export function highlight(text, matchedTerms) {
  const terms = Array.from(matchedTerms || [])
  if (terms.length === 0) return [{ text, hit: false }]

  const pattern = terms
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')

  const splitter = new RegExp(`(${pattern})`, 'gi')
  const exact = new RegExp(`^(?:${pattern})$`, 'i')

  return text
    .split(splitter)
    .filter((part) => part !== '')
    .map((part) => ({ text: part, hit: exact.test(part) }))
}
