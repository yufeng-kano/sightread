import { describe, expect, it } from 'vitest'
import { nodesToMarkdown, type MarkdownNode } from './copy'

/** Minimal DOM stand-ins — the serializer reads a structural subset of `Node`. */
function el(
  tagName: string,
  attrs: Record<string, string> = {},
  childNodes: MarkdownNode[] = [],
): MarkdownNode {
  return {
    nodeType: 1,
    tagName: tagName.toUpperCase(),
    childNodes,
    getAttribute: (name: string) => attrs[name] ?? null,
    textContent: childNodes.map((child) => child.textContent ?? '').join(''),
  }
}

function text(content: string): MarkdownNode {
  return { nodeType: 3, textContent: content }
}

function mathSpan(tex: string, rendered: string): MarkdownNode {
  return el('span', { class: 'md-inline-math', 'data-tex': tex }, [text(rendered)])
}

describe('nodesToMarkdown', () => {
  it('turns a table back into a pipe table, math and escaped pipes included', () => {
    const table = el('table', { class: 'md-table' }, [
      el('thead', {}, [
        el('tr', {}, [
          el('th', {}, [text('Name')]),
          el('th', {}, [text('Value')]),
        ]),
      ]),
      el('tbody', {}, [
        el('tr', {}, [
          el('td', {}, [text('H'), mathSpan('$_2$', '2'), text('O')]),
          el('td', {}, [text('a|b')]),
        ]),
      ]),
    ])

    expect(nodesToMarkdown([el('div', { class: 'md-table-wrap' }, [table])])).toBe(
      ['| Name | Value |', '| --- | --- |', '| H$_2$O | a\\|b |'].join('\n'),
    )
  })

  it('gives a partial table selection a separator so it stays a table', () => {
    const partial = el('table', {}, [
      el('tbody', {}, [
        el('tr', {}, [el('td', {}, [text('EMEA')]), el('td', {}, [text('903')])]),
      ]),
    ])

    expect(nodesToMarkdown([partial])).toBe(['| EMEA | 903 |', '| --- | --- |'].join('\n'))
  })

  it('serializes headings, lists, code and display math by their viewer classes', () => {
    const nodes = [
      el('h3', { class: 'md-h2' }, [text('Results')]),
      el('ol', { start: '5', class: 'md-list' }, [
        el('li', {}, [text('Fifth')]),
        el('li', {}, [text('Sixth')]),
      ]),
      el('pre', { class: 'md-math' }, [text('E = mc^2')]),
      el('pre', { class: 'md-math' }, [
        el('code', { class: 'language-python' }, [text('print(1)')]),
      ]),
    ]

    expect(nodesToMarkdown(nodes)).toBe(
      [
        '## Results',
        '5. Fifth\n6. Sixth',
        '$$\nE = mc^2\n$$',
        '```python\nprint(1)\n```',
      ].join('\n\n'),
    )
  })

  it('hands a figure back as its stored placeholder source', () => {
    const figure = el(
      'figure',
      { class: 'md-figure', 'data-md': '![fig1](sightread://p3/10,20,30,40)\nFigure 1: chart' },
      [el('div', { class: 'figure-frame' }, [text('No stored crop for this figure')])],
    )

    expect(nodesToMarkdown([figure])).toBe('![fig1](sightread://p3/10,20,30,40)\nFigure 1: chart')
  })

  it('keeps a selection inside one paragraph as one line of text', () => {
    const nodes = [text('Qingwen Bu'), mathSpan('$^{1,2}$', '1,2'), text(' and others')]

    expect(nodesToMarkdown(nodes)).toBe('Qingwen Bu$^{1,2}$ and others')
  })

  it('separates whole blocks with blank lines and drops page markers', () => {
    const section = el('section', { class: 'page' }, [
      el('p', { class: 'eyebrow sm page-marker' }, [text('Page 1')]),
      el('article', { class: 'prose' }, [
        el('h4', { class: 'md-h3' }, [text('Notes')]),
        el('p', { class: 'md-p' }, [text('Body text.')]),
      ]),
    ])

    expect(nodesToMarkdown([section])).toBe('### Notes\n\nBody text.')
  })
})
