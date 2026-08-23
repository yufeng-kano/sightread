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
 * transcription prompt asks the model for: headings, paragraphs, lists, pipe tables and
 * figure placeholders (docs/parsing.md § Prompt). Anything else stays a paragraph, which
 * renders as its own source text rather than disappearing.
 */

/** `[ymin, xmin, ymax, xmax]`, 0–1000 normalized — the `bbox_format` the result declares. */
export type Bbox = [number, number, number, number]

export type ResultBlock =
  | { kind: 'h2'; text: string }
  | { kind: 'h3'; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'math'; text: string }
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
      page().blocks.push({
        kind: (heading[1] ?? '').length >= 3 ? 'h3' : 'h2',
        text: (heading[2] ?? '').trim(),
      })
      continue
    }

    // A list before the paragraph fallback: merged into prose, `- First` / `- Second`
    // becomes the single line "- First - Second", losing both the structure and the
    // markers the model was asked to produce.
    const listItem = LIST_ITEM.exec(line)
    if (listItem) {
      const ordered = isOrdered(listItem[1] ?? '')
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
      page().blocks.push({ kind: 'list', ordered, items })
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
