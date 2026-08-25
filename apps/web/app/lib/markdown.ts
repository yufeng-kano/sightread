/**
 * The result document, as blocks the viewer can render.
 *
 * `GET /api/jobs/{id}/result` hands back the whole document as one markdown string with
 * `<!-- page: N -->` markers between pages and `![figN](sightread://pN/…)` placeholders
 * where figures belong (docs/parsing.md § Page markers). The viewer needs it the other way
 * round — ordered blocks grouped by page — so the split happens here, on the client, rather
 * than being asked of an API whose contract is the markdown itself.
 *
 * This is deliberately not a general markdown parser. It understands exactly the shapes the
 * transcription prompt asks the model for: headings, paragraphs, lists, pipe tables, fenced
 * code, display math and figure placeholders (docs/parsing.md § Prompt). Anything else stays
 * a paragraph, which renders as its own source text rather than disappearing.
 *
 * It is also flat, and knowingly so: a nested list comes out as one level, inline emphasis
 * comes out as its source characters, and a fence is closed by any fence rather than by a
 * matching one — so a `~~~` block containing a literal ``` line ends early. The content
 * survives, the structure does not. The alternative is not a deeper version of this — it is
 * rendering through a real GFM parser, which is a dependency and a sanitisation decision
 * (docs/web.md § Result viewer).
 */

/** `[ymin, xmin, ymax, xmax]`, 0–1000 normalized — the `bbox_format` the result declares. */
export type Bbox = [number, number, number, number]

export type ResultBlock =
  /** `level` is the source depth (`#…` count) — the viewer draws two heading sizes, but a
   *  copy must hand the original level back (docs/web.md § Result viewer). */
  | { kind: 'h2'; text: string; level: number }
  | { kind: 'h3'; text: string; level: number }
  | { kind: 'p'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[]; start?: number }
  | { kind: 'math'; text: string }
  | { kind: 'code'; text: string; lang: string | null }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'fig'; id: string; bbox: Bbox; caption: string | null }

export interface ResultPageBlocks {
  page: number
  blocks: ResultBlock[]
  /** Shown beside the page in the viewer's rail, so a reader can find the figures. */
  figureCount: number
}

const PAGE_MARKER = /^<!--\s*page:\s*(\d+)\s*-->$/
const FIGURE = /^!\[([^\]\n]*)\]\(\s*sightread:\/\/p(\d+)\/(-?\d+),(-?\d+),(-?\d+),(-?\d+)\s*\)$/
const HEADING = /^(#{1,6})\s+(.*)$/
const COMMENT = /^<!--.*-->$/
/** `- item`, `* item`, `+ item`, `1. item`, `2) item`. */
const LIST_ITEM = /^([-*+]|\d{1,9}[.)])\s+(.*)$/
/** A display-math fence: `$$` alone on its line. */
const MATH_FENCE = '$$'
/** A fenced code block's opening or closing line, with its optional info string. */
const CODE_FENCE = /^(?:```|~~~)\s*([^\s`]*)\s*$/

/** A pipe table's separator row: `| --- | :--: |`, with or without the outer pipes. */
function isTableRule(line: string): boolean {
  return /^\|?[\s|:-]+\|[\s|:-]*$/.test(line) && line.includes('-')
}

/**
 * A table is its header row *plus* the separator under it — GFM makes the outer pipes
 * optional, so `Name | Value` over `--- | ---` is as valid as the fully piped form and the
 * only reliable marker is the separator. Looking one line ahead is what lets both forms in
 * without treating every sentence containing a pipe as a table.
 */
function isTableStart(line: string, next: string): boolean {
  return line.includes('|') && isTableRule(next)
}

/** `1.` and `2)` are ordered; `-`, `*` and `+` are not. */
function isOrdered(marker: string): boolean {
  return !'-*+'.includes(marker)
}

/**
 * Every line that starts a block of its own — so a paragraph knows where to stop. `next` is
 * the line after it, which only the table check needs.
 */
function startsBlock(line: string, next = ''): boolean {
  return (
    !line ||
    line === MATH_FENCE ||
    CODE_FENCE.test(line) ||
    isTableStart(line, next) ||
    line.startsWith('#') ||
    LIST_ITEM.test(line) ||
    FIGURE.test(line) ||
    PAGE_MARKER.test(line) ||
    COMMENT.test(line)
  )
}

/**
 * Splits on the pipes that separate columns, which is not every pipe: GFM escapes a literal
 * one as `\|`, and splitting on that both invents a column and leaves the backslash on
 * screen. The outer pipes are optional, so they are only trimmed when present.
 */
function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, '')
    .replace(/(?<!\\)\|\s*$/, '')
    .split(/(?<!\\)\|/)
    .map((cell) => cell.trim().replace(/\\\|/g, '|'))
}

/**
 * Groups the document by page marker. Content before the first marker — a result stored
 * before the pipeline wrote them, say — is kept as page 1 rather than dropped: the viewer
 * would otherwise show an empty document for a job that has one.
 */
export function parseResultMarkdown(markdown: string): ResultPageBlocks[] {
  const pages: ResultPageBlocks[] = []
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n')

  let current: ResultPageBlocks | null = null

  function page(): ResultPageBlocks {
    if (!current) {
      current = { page: 1, blocks: [], figureCount: 0 }
      pages.push(current)
    }
    return current
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = (lines[index] ?? '').trim()

    const marker = PAGE_MARKER.exec(line)
    if (marker) {
      const number = Number(marker[1])
      // A marker for the page already open (the leading-content case above) continues it
      // rather than starting an empty duplicate.
      if (!current || current.page !== number) {
        current = { page: number, blocks: [], figureCount: 0 }
        pages.push(current)
      }
      continue
    }

    if (!line || COMMENT.test(line)) {
      continue
    }

    const figure = FIGURE.exec(line)
    if (figure) {
      const target = page()
      // The caption is written verbatim on the next line, and only there — anything that
      // starts another block is the next block, not this figure's caption.
      const next = (lines[index + 1] ?? '').trim()
      const captioned = Boolean(next) && !startsBlock(next, (lines[index + 2] ?? '').trim())
      if (captioned) {
        index += 1
      }
      target.blocks.push({
        kind: 'fig',
        id: figure[1] || `fig${target.figureCount + 1}`,
        bbox: [Number(figure[3]), Number(figure[4]), Number(figure[5]), Number(figure[6])],
        caption: captioned ? next : null,
      })
      target.figureCount += 1
      continue
    }

    // Code, like math, is content whose line breaks and indentation are the point. The
    // prompt tells the model not to wrap its *answer* in a fence, so a fence that does
    // arrive is a code block the page carried.
    const codeFence = CODE_FENCE.exec(line)
    if (codeFence) {
      const rows: string[] = []
      let cursor = index + 1
      while (
        cursor < lines.length &&
        !CODE_FENCE.test((lines[cursor] ?? '').trim()) &&
        !PAGE_MARKER.test((lines[cursor] ?? '').trim())
      ) {
        rows.push((lines[cursor] ?? '').trimEnd())
        cursor += 1
      }
      index = CODE_FENCE.test((lines[cursor] ?? '').trim()) ? cursor : cursor - 1
      page().blocks.push({ kind: 'code', text: rows.join('\n'), lang: codeFence[1] || null })
      continue
    }

    // Display math is the one block whose line breaks *are* its content: an aligned group
    // of equations joined into a paragraph is no longer the formula the page carried, and
    // the prompt asks for formulas to be kept.
    if (line === MATH_FENCE) {
      const rows: string[] = []
      let cursor = index + 1
      // A page marker closes an unclosed fence: a model that forgets the closing `$$` must
      // not swallow the rest of the document into one formula.
      while (
        cursor < lines.length &&
        (lines[cursor] ?? '').trim() !== MATH_FENCE &&
        !PAGE_MARKER.test((lines[cursor] ?? '').trim())
      ) {
        rows.push((lines[cursor] ?? '').trimEnd())
        cursor += 1
      }
      // Past the closing fence, or back onto the page marker so the next pass sees it.
      index = (lines[cursor] ?? '').trim() === MATH_FENCE ? cursor : cursor - 1
      page().blocks.push({ kind: 'math', text: rows.join('\n') })
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      const level = (heading[1] ?? '').length
      page().blocks.push({
        kind: level >= 3 ? 'h3' : 'h2',
        text: (heading[2] ?? '').trim(),
        level,
      })
      continue
    }

    // A list before the paragraph fallback: merged into prose, `- First` / `- Second`
    // becomes the single line "- First - Second", losing both the structure and the
    // markers the model was asked to produce.
    const listItem = LIST_ITEM.exec(line)
    if (listItem) {
      const marker = listItem[1] ?? ''
      const ordered = isOrdered(marker)
      // A list continued from the previous page starts at 5, not at 1, and renumbering it
      // changes what the document says.
      const start = ordered ? Number.parseInt(marker, 10) : Number.NaN
      const items: string[] = []
      let cursor = index
      while (cursor < lines.length) {
        const raw = lines[cursor] ?? ''
        const trimmed = raw.trim()

        // One block per marker kind: a bulleted list directly under a numbered one is two
        // lists, not one with a confused type.
        const match = LIST_ITEM.exec(trimmed)
        if (match) {
          if (isOrdered(match[1] ?? '') !== ordered) {
            break
          }
          items.push((match[2] ?? '').trim())
          cursor += 1
          continue
        }

        // An indented line that starts no block of its own is the rest of the item above
        // it — a wrapped item is one item, not an item and a stray paragraph.
        const continues =
          items.length > 0 &&
          /^\s+\S/.test(raw) &&
          !startsBlock(trimmed, (lines[cursor + 1] ?? '').trim())
        if (!continues) {
          break
        }
        items[items.length - 1] += ` ${trimmed}`
        cursor += 1
      }
      index = cursor - 1
      page().blocks.push({
        kind: 'list',
        ordered,
        items,
        ...(Number.isFinite(start) && start !== 1 ? { start } : {}),
      })
      continue
    }

    // `isTableStart` for both forms, with no shortcut for a leading pipe: the prompt asks
    // for formulas, and `|x| = 3` is a line of maths, not a header-only table.
    if (isTableStart(line, (lines[index + 1] ?? '').trim())) {
      const rows: string[][] = []
      let cursor = index
      while (cursor < lines.length) {
        const row = (lines[cursor] ?? '').trim()
        // A row is anything still carrying a pipe. Once the pipes stop, so does the table —
        // the prose under it is the next block.
        if (!row.includes('|')) {
          break
        }
        if (!isTableRule(row)) {
          rows.push(splitRow(row))
        }
        cursor += 1
      }
      index = cursor - 1
      const [header, ...body] = rows
      page().blocks.push({ kind: 'table', header: header ?? [], rows: body })
      continue
    }

    // Everything else is prose: consecutive lines are one paragraph, as in markdown.
    const paragraph: string[] = [line]
    let cursor = index + 1
    while (cursor < lines.length) {
      const next = (lines[cursor] ?? '').trim()
      if (startsBlock(next, (lines[cursor + 1] ?? '').trim())) {
        break
      }
      paragraph.push(next)
      cursor += 1
    }
    index = cursor - 1
    page().blocks.push({ kind: 'p', text: paragraph.join(' ') })
  }

  return pages
}

/** `[ymin, xmin, ymax, xmax]` as the caption prints it, beside the figure's name. */
export function formatBbox(bbox: Bbox): string {
  return `[${bbox.join(',')}]`
}

// --- inline math ------------------------------------------------------------------------
//
// Transcriptions carry inline TeX the way papers do — `Qingwen Bu$^{1,2}$`, `H$_2$O` — and
// showing the source characters makes an author line read like a syntax error. This is
// affiliation-marker-grade math, not a TeX engine: superscripts, subscripts, the
// `\text`-family wrappers and a short symbol table. Anything unrecognized keeps its source
// characters, and display math stays a verbatim block (docs/web.md § Result viewer).

/** One run inside a rendered math span: plain, superscript or subscript. */
export interface MathToken {
  kind: 'text' | 'sup' | 'sub'
  text: string
}

export type InlineSegment =
  | { kind: 'text'; text: string }
  /** `tex` is the source between the dollars, verbatim — copy-as-markdown reads it back. */
  | { kind: 'math'; tex: string; tokens: MathToken[] }

/** Wrappers whose braces mean "typeset this normally" — the content is kept, the command
 *  dropped. `operatorname` is the odd one out but appears in transcriptions. */
const TEXT_WRAPPERS = new Set(['text', 'textrm', 'textit', 'textbf', 'mathrm', 'mathbf', 'mathit', 'mathsf', 'mathcal', 'operatorname'])

/** The symbols vision transcriptions actually produce. Unknown commands stay verbatim —
 *  a wrong glyph is worse than visible TeX. */
const MATH_SYMBOLS: Record<string, string> = {
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', varepsilon: 'ε',
  zeta: 'ζ', eta: 'η', theta: 'θ', iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ',
  nu: 'ν', xi: 'ξ', pi: 'π', rho: 'ρ', sigma: 'σ', tau: 'τ', upsilon: 'υ',
  phi: 'φ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π', Sigma: 'Σ',
  Upsilon: 'Υ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
  times: '×', cdot: '·', pm: '±', mp: '∓', div: '÷', leq: '≤', le: '≤', geq: '≥',
  ge: '≥', neq: '≠', ne: '≠', approx: '≈', sim: '~', propto: '∝', infty: '∞',
  rightarrow: '→', to: '→', leftarrow: '←', leftrightarrow: '↔', Rightarrow: '⇒',
  degree: '°', circ: '∘', bullet: '•', star: '★', dagger: '†', ddagger: '‡',
  ldots: '…', dots: '…', cdots: '⋯', prime: '′', partial: '∂', nabla: '∇',
  sum: 'Σ', prod: 'Π', int: '∫', sqrt: '√', in: '∈', notin: '∉', subset: '⊂',
  cup: '∪', cap: '∩', forall: '∀', exists: '∃', emptyset: '∅', angle: '∠',
  percent: '%', '%': '%', '&': '&', '#': '#', _: '_', '{': '{', '}': '}', '$': '$',
  ',': ' ', ';': ' ', quad: ' ', qquad: ' ',
}

/** `{…}` balanced from `start` (which must point at the `{`), else the single char or
 *  `\command` there. Returns the argument's content and the index just past it. */
function readArgument(tex: string, start: number): [string, number] {
  if (tex[start] === '{') {
    let depth = 0
    for (let index = start; index < tex.length; index += 1) {
      if (tex[index] === '{') depth += 1
      if (tex[index] === '}') {
        depth -= 1
        if (depth === 0) {
          return [tex.slice(start + 1, index), index + 1]
        }
      }
    }
    // Unbalanced: everything to the end is the argument, which at least loses nothing.
    return [tex.slice(start + 1), tex.length]
  }
  if (tex[start] === '\\') {
    const match = /^\\[a-zA-Z]+/.exec(tex.slice(start))
    if (match) {
      return [match[0], start + match[0].length]
    }
    return [tex.slice(start, start + 2), start + 2]
  }
  return [tex[start] ?? '', start + 1]
}

function pushToken(out: MathToken[], kind: MathToken['kind'], text: string) {
  if (!text) {
    return
  }
  const last = out[out.length - 1]
  if (last && last.kind === kind) {
    last.text += text
  } else {
    out.push({ kind, text })
  }
}

/** Flattens one TeX run into renderable tokens. Scripts inside scripts flatten to the
 *  outer kind — `x^{y^z}` is beyond what this reader promises to draw. */
function tokenizeMath(tex: string, kind: MathToken['kind'], out: MathToken[]): void {
  let index = 0
  while (index < tex.length) {
    const char = tex[index] ?? ''
    if ((char === '^' || char === '_') && kind === 'text') {
      const [argument, next] = readArgument(tex, index + 1)
      tokenizeMath(argument, char === '^' ? 'sup' : 'sub', out)
      index = next
      continue
    }
    if (char === '\\') {
      const [command, next] = readArgument(tex, index)
      const name = command.slice(1)
      if (TEXT_WRAPPERS.has(name) && tex[next] === '{') {
        const [argument, past] = readArgument(tex, next)
        tokenizeMath(argument, kind, out)
        index = past
      } else if (name in MATH_SYMBOLS) {
        pushToken(out, kind, MATH_SYMBOLS[name] ?? '')
        index = next
      } else {
        // Unknown command: keep it readable as source — including its braced arguments'
        // delimiters, or `\frac{a}{b}` collapses into `\fracab`.
        pushToken(out, kind, command)
        let cursor = next
        while (tex[cursor] === '{') {
          const [argument, past] = readArgument(tex, cursor)
          pushToken(out, kind, '{')
          tokenizeMath(argument, kind, out)
          pushToken(out, kind, '}')
          cursor = past
        }
        index = cursor
      }
      continue
    }
    if (char === '{' || char === '}') {
      index += 1
      continue
    }
    pushToken(out, kind, char)
    index += 1
  }
}

/** A `$…$` span anchored at one candidate opener: closes on `$` not followed by a digit —
 *  so "$5 and $6" stays two prices, not a formula. */
const MATH_SPAN_AT = /^\$([^$\n]+)\$(?!\d)/

/**
 * Splits one line of prose (a paragraph, heading, list item, table cell or caption) into
 * plain text and rendered math spans.
 *
 * Scanned dollar by dollar rather than with one global regex on purpose: a rejected
 * candidate (a price, a span padded with spaces) resumes just past its *opening* dollar —
 * a global match would have consumed the next span's opener as its own closer, so
 * "cost $5 and variable $x$" would lose the real formula.
 */
export function parseInline(text: string): InlineSegment[] {
  const segments: InlineSegment[] = []
  let cursor = 0
  let scan = 0
  while (scan < text.length) {
    const open = text.indexOf('$', scan)
    if (open === -1) {
      break
    }
    const match = MATH_SPAN_AT.exec(text.slice(open))
    const tex = match?.[1] ?? ''
    if (!match || /^\s/.test(tex) || /\s$/.test(tex)) {
      scan = open + 1
      continue
    }
    if (open > cursor) {
      segments.push({ kind: 'text', text: text.slice(cursor, open) })
    }
    const tokens: MathToken[] = []
    tokenizeMath(tex, 'text', tokens)
    segments.push({ kind: 'math', tex, tokens })
    cursor = open + match[0].length
    scan = cursor
  }
  if (cursor < text.length || segments.length === 0) {
    segments.push({ kind: 'text', text: text.slice(cursor) })
  }
  return segments
}
