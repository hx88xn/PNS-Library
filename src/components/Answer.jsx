import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * An answer, rendered as the markdown the model actually writes.
 *
 * It was previously split on blank lines into paragraphs, so a list arrived as
 * a run of hyphens, a table as a wall of pipes, and `**not less than 0.055
 * m·rad**` with its asterisks showing. The prompt asks for the register of a
 * design office memorandum and the model obliges in markdown; this reads it.
 *
 * react-markdown rather than a markdown-to-HTML library, and the distinction is
 * a safety property rather than a preference. This text is generated from a
 * corpus the office ingests, so a document containing markup is an untrusted
 * input path. react-markdown builds React elements and never parses raw HTML,
 * which makes injection structurally impossible instead of a thing to remember
 * to sanitise. `dangerouslySetInnerHTML` with model output over a RESTRICTED
 * corpus is not a trade worth making for a smaller bundle.
 *
 * GFM is on for tables. Classification rules are full of them, and a table
 * flattened to pipes is the one case where the answer is present but unreadable.
 */
export default function Answer({ text }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Tables get a scroll container of their own. A wide one would
        // otherwise stretch the bubble and force the whole thread sideways.
        table: ({ node, ...props }) => (
          <div className="md-table-wrap">
            <table {...props} />
          </div>
        ),
        // Links are rendered as plain text. Nothing in an air-gapped library
        // is reachable, and a link that cannot be followed is a promise the
        // application cannot keep — citations are the way to a source, and
        // they are handled separately under the answer.
        a: ({ node, children, ...props }) => <span {...props}>{children}</span>
      }}
    >
      {text}
    </Markdown>
  )
}
