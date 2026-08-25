/**
 * Copy-as-markdown: turns the selected part of the rendered document back into the
 * markdown it was rendered from (docs/web.md § Result viewer).
 *
 * The serializer walks the *cloned selection fragment* — `Range.cloneContents()` — so a
 * partial table selection arrives as a partial table and comes out as a valid partial pipe
 * table. Structure is recognized by the viewer's own block classes and data attributes:
 * `data-tex` gives inline math back as `$…$`, `data-md` gives a figure back as its
 * placeholder, and everything unrecognized falls through to its text.
 *
 * Written against a structural subset of the DOM (`MarkdownNode`) rather than `Node`, so
 * the logic is unit-testable in the framework-free node suite (docs/testing.md).
 */

const TEXT_NODE = 3
const ELEMENT_NODE = 1

/** The subset of `Node`/`Element` the serializer reads. Real DOM nodes satisfy it. */
export interface MarkdownNode {
  nodeType: number
  textContent?: string | null
  childNodes?: ArrayLike<MarkdownNode>
  tagName?: string
  getAttribute?: (name: string) => string | null
}

function children(node: MarkdownNode): MarkdownNode[] {
  return Array.from(node.childNodes ?? [])
}

function attribute(node: MarkdownNode, name: string): string | null {
  return node.getAttribute ? node.getAttribute(name) : null
}

function classes(node: MarkdownNode): string[] {
  return (attribute(node, 'class') ?? '').split(/\s+/).filter(Boolean)
}

function tag(node: MarkdownNode): string {
  return (node.tagName ?? '').toLowerCase()
}

/** Inline content: text runs plus math spans, which come back as their `data-tex`. */
function inlineText(node: MarkdownNode): string {
  if (node.nodeType === TEXT_NODE) {
    return node.textContent ?? ''
  }
  if (node.nodeType !== ELEMENT_NODE) {
    return ''
  }
  const tex = attribute(node, 'data-tex')
  if (tex !== null) {
    return tex
  }
  return children(node).map(inlineText).join('')
}

/** A table cell's markdown: inline content with its pipes escaped, on one line. */
function cellText(node: MarkdownNode): string {
  return inlineText(node).replace(/\s+/g, ' ').trim().replace(/\|/g, '\\|')
}

function tableRows(node: MarkdownNode): MarkdownNode[] {
  const rows: MarkdownNode[] = []
  for (const child of children(node)) {
    if (tag(child) === 'tr') {
      rows.push(child)
    } else {
      rows.push(...tableRows(child))
    }
  }
  return rows
}

function rowsToMarkdown(rows: MarkdownNode[]): string {
  const lines: string[] = []
  for (const [index, row] of rows.entries()) {
    const cells = children(row).filter((cell) => tag(cell) === 'th' || tag(cell) === 'td')
    if (!cells.length) {
      continue
    }
    lines.push(`| ${cells.map(cellText).join(' | ')} |`)
    // The separator goes under the first row: a partial selection may not include the
    // real header, but a pipe table without a separator is not a table to a renderer.
    if (index === 0) {
      lines.push(`| ${cells.map(() => '---').join(' | ')} |`)
    }
  }
  return lines.join('\n')
}

function tableToMarkdown(node: MarkdownNode): string {
  return rowsToMarkdown(tableRows(node))
}

function listToMarkdown(node: MarkdownNode): string {
  const ordered = tag(node) === 'ol'
  const start = Number.parseInt(attribute(node, 'start') ?? '1', 10) || 1
  const items = children(node).filter((child) => tag(child) === 'li')
  return items
    .map((item, index) => {
      const marker = ordered ? `${start + index}.` : '-'
      return `${marker} ${inlineText(item).replace(/\s+/g, ' ').trim()}`
    })
    .join('\n')
}

function codeToMarkdown(node: MarkdownNode): string {
  const code = children(node).find((child) => tag(child) === 'code')
  if (code) {
    const language =
      classes(code)
        .find((name) => name.startsWith('language-'))
        ?.slice('language-'.length) ?? ''
    return `\`\`\`${language}\n${code.textContent ?? ''}\n\`\`\``
  }
  // No <code> child: the viewer's display-math block.
  return `$$\n${node.textContent ?? ''}\n$$`
}

/** One block element's markdown, or null to fall through to its children. */
function blockToMarkdown(node: MarkdownNode): string | null {
  const source = attribute(node, 'data-md')
  if (source !== null) {
    return source
  }
  const names = classes(node)
  // The viewer's page labels are navigation, not document content.
  if (names.includes('page-marker') || names.includes('page-rail')) {
    return ''
  }
  if (names.includes('md-h2') || names.includes('md-h3')) {
    // The viewer draws two heading sizes, but the source depth rides on `data-level` —
    // copying `# Title` must not demote it to `##`, nor `####` promote to `###`.
    const fallback = names.includes('md-h2') ? 2 : 3
    const level = Number.parseInt(attribute(node, 'data-level') ?? '', 10) || fallback
    return `${'#'.repeat(level)} ${inlineText(node).trim()}`
  }
  switch (tag(node)) {
    case 'table':
      return tableToMarkdown(node)
    case 'ul':
    case 'ol':
      return listToMarkdown(node)
    case 'pre':
      return codeToMarkdown(node)
    case 'p':
      return inlineText(node).replace(/\s+/g, ' ').trim()
    default:
      return null
  }
}

/** Tags that carry inline content — a selection inside one paragraph arrives as these. */
const INLINE_TAGS = new Set(['span', 'sup', 'sub', 'em', 'strong', 'i', 'b', 'a', 'code', 'br'])

function isInline(node: MarkdownNode): boolean {
  if (node.nodeType === TEXT_NODE) {
    return true
  }
  if (node.nodeType !== ELEMENT_NODE || attribute(node, 'data-md') !== null) {
    return false
  }
  return INLINE_TAGS.has(tag(node))
}

interface Walk {
  blocks: string[]
  inline: string[]
}

function flush(walk: Walk): void {
  const text = walk.inline.join('').replace(/\s+/g, ' ').trim()
  if (text) {
    walk.blocks.push(text)
  }
  walk.inline = []
}

/**
 * A selection confined to one table or list is cloned *without* its structural root:
 * `Range.cloneContents()` copies the parent chain only up to — exclusive of — the range's
 * common ancestor, so dragging across a table hands over bare `thead`/`tbody`/`tr` (or
 * `td` for one row), and a multi-item list hands over bare `li`. These runs are
 * reassembled here into the table or list their parent would have made of them.
 */
const TABLE_PARTS = new Set(['thead', 'tbody', 'tfoot', 'tr'])
const CELL_PARTS = new Set(['td', 'th'])

function orphanGroup(node: MarkdownNode): 'rows' | 'cells' | 'items' | null {
  if (node.nodeType !== ELEMENT_NODE) {
    return null
  }
  const name = tag(node)
  if (TABLE_PARTS.has(name)) {
    return 'rows'
  }
  if (CELL_PARTS.has(name)) {
    return 'cells'
  }
  if (name === 'li') {
    return 'items'
  }
  return null
}

/** What the selection's own DOM knows about the list its cloned `li` runs fell out of —
 *  computed by the copy handler from the live range, since the clone no longer holds it. */
export interface OrphanListContext {
  ordered: boolean
  /** The number the first selected item carries in the live list. */
  start: number
}

function orphansToMarkdown(
  kind: 'rows' | 'cells' | 'items',
  group: MarkdownNode[],
  list?: OrphanListContext,
): string {
  if (kind === 'rows') {
    return rowsToMarkdown(group.flatMap((part) => (tag(part) === 'tr' ? [part] : tableRows(part))))
  }
  if (kind === 'cells') {
    // Cells with no row: one row's worth of a table.
    return rowsToMarkdown([{ nodeType: ELEMENT_NODE, tagName: 'TR', childNodes: group }])
  }
  // Items with no list: the live selection's context says what the ancestor was — an
  // ordered run keeps its numbering. Without context, bullets.
  return group
    .map((item, index) => {
      const marker = list?.ordered ? `${list.start + index}.` : '-'
      return `${marker} ${inlineText(item).replace(/\s+/g, ' ').trim()}`
    })
    .join('\n')
}

function walkNodes(nodes: MarkdownNode[], walk: Walk, list?: OrphanListContext): void {
  let index = 0
  while (index < nodes.length) {
    const node = nodes[index]!
    const kind = orphanGroup(node)
    if (kind !== null) {
      // Consecutive orphaned parts are one structure, not a block each; formatting
      // whitespace between them does not break the run.
      const group: MarkdownNode[] = []
      while (index < nodes.length) {
        const candidate = nodes[index]!
        if (orphanGroup(candidate) === kind) {
          group.push(candidate)
          index += 1
          continue
        }
        if (candidate.nodeType === TEXT_NODE && !(candidate.textContent ?? '').trim()) {
          index += 1
          continue
        }
        break
      }
      flush(walk)
      const block = orphansToMarkdown(kind, group, list)
      if (block) {
        walk.blocks.push(block)
      }
      continue
    }
    walkNode(node, walk)
    index += 1
  }
}

function walkNode(node: MarkdownNode, walk: Walk): void {
  // Consecutive inline runs — text and math spans from inside one paragraph — stay one
  // line rather than becoming a block each.
  if (isInline(node)) {
    walk.inline.push(inlineText(node))
    return
  }
  if (node.nodeType !== ELEMENT_NODE) {
    return
  }
  const block = blockToMarkdown(node)
  if (block !== null) {
    flush(walk)
    if (block) {
      walk.blocks.push(block)
    }
    return
  }
  // A container (section, article, div): its children are blocks of their own.
  flush(walk)
  walkNodes(children(node), walk)
  flush(walk)
}

/**
 * The selection fragment as markdown. A selection inside one paragraph comes back as the
 * plain text it looks like (math spans as their `$…$`); anything structural comes back as
 * source a markdown editor will re-render — including a selection whose table or list
 * root the range clone left behind. `list` is that lost root's context, when the caller
 * could read it off the live selection — it only affects top-level orphaned `li` runs.
 */
export function nodesToMarkdown(nodes: ArrayLike<MarkdownNode>, list?: OrphanListContext): string {
  const walk: Walk = { blocks: [], inline: [] }
  walkNodes(Array.from(nodes), walk, list)
  flush(walk)
  return walk.blocks.join('\n\n')
}
