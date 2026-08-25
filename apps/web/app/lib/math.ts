/**
 * KaTeX rendering for the result viewer (docs/web.md § Result viewer).
 *
 * One function, one policy: TeX that KaTeX can typeset renders as math; TeX it cannot
 * parse returns null and the caller falls back to the verbatim source — a wrong glyph is
 * worse than visible TeX, so `throwOnError` stays on and the failure is the signal.
 * KaTeX escapes its input and `trust` is off, so the returned HTML is inert markup.
 */
import katex from 'katex'

/** Commands transcriptions produce that KaTeX does not define. */
const MACROS: Record<string, string> = {
  '\\degree': '^{\\circ}',
}

/** KaTeX HTML for one TeX source, or null when KaTeX cannot parse it. */
export function renderTexHtml(tex: string, displayMode: boolean): string | null {
  try {
    return katex.renderToString(tex, {
      displayMode,
      throwOnError: true,
      // Warnings (about unicode in math mode, say) are not errors — render anyway,
      // and keep them out of the console.
      strict: 'ignore',
      macros: MACROS,
    })
  } catch {
    return null
  }
}
