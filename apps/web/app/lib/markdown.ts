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
 * transcription prompt produces: headings, paragraphs, pipe tables and figure placeholders.
 * Anything else stays a paragraph, which renders as its own source text rather than
 * disappearing.
 */

/** `[ymin, xmin, ymax, xmax]`, 0–1000 normalized — the `bbox_format` the result declares. */
export type Bbox = [number, number, number, number]

export type ResultBlock =
  | { kind: 'h2'; text: string }
  | { kind: 'h3'; text: string }
  | { kind: 'p'; text: string }
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

/** A pipe table's separator row: `| --- | :--: |`. */
function isTableRule(line: string): boolean {
  return /^\|?[\s|:-]+\|[\s|:-]*$/.test(line) && line.includes('-')
}

function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim())
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
      const captioned = next && !next.startsWith('|') && !next.startsWith('#') && !FIGURE.test(next) && !PAGE_MARKER.test(next) && !COMMENT.test(next)
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

    const heading = HEADING.exec(line)
    if (heading) {
      page().blocks.push({
        kind: (heading[1] ?? '').length >= 3 ? 'h3' : 'h2',
        text: (heading[2] ?? '').trim(),
      })
      continue
    }

    if (line.startsWith('|')) {
      const rows: string[][] = []
      let cursor = index
      while (cursor < lines.length && (lines[cursor] ?? '').trim().startsWith('|')) {
        const row = (lines[cursor] ?? '').trim()
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
      if (!next || next.startsWith('|') || next.startsWith('#') || FIGURE.test(next) || PAGE_MARKER.test(next) || COMMENT.test(next)) {
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
