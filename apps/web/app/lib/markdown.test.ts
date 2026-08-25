import { describe, expect, it } from 'vitest'
import { formatBbox, parseInline, parseResultMarkdown } from './markdown'

describe('parseResultMarkdown', () => {
  it('splits on page markers and keeps block order', () => {
    const pages = parseResultMarkdown(
      [
        '<!-- page: 1 -->',
        '## Quarterly results',
        '',
        'Revenue grew across every region,',
        'led by APAC.',
        '',
        '<!-- page: 2 -->',
        '### Notes',
        '| Region | Revenue |',
        '| --- | --- |',
        '| APAC | 1,204 |',
        '| EMEA | 903 |',
      ].join('\n'),
    )

    expect(pages.map((page) => page.page)).toEqual([1, 2])
    expect(pages[0]!.blocks).toEqual([
      { kind: 'h2', text: 'Quarterly results', level: 2 },
      { kind: 'p', text: 'Revenue grew across every region, led by APAC.' },
    ])
    expect(pages[1]!.blocks).toEqual([
      { kind: 'h3', text: 'Notes', level: 3 },
      {
        kind: 'table',
        header: ['Region', 'Revenue'],
        rows: [
          ['APAC', '1,204'],
          ['EMEA', '903'],
        ],
      },
    ])
  })

  it('reads a figure placeholder and the caption on the next line', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 3 -->', '![fig1](sightread://p3/120,60,480,940)', 'Figure 1: revenue by region'].join('\n'),
    )

    expect(pages[0]!.figureCount).toBe(1)
    expect(pages[0]!.blocks).toEqual([
      {
        kind: 'fig',
        id: 'fig1',
        bbox: [120, 60, 480, 940],
        caption: 'Figure 1: revenue by region',
      },
    ])
  })

  it('leaves a figure uncaptioned when the next line starts another block', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', '![fig1](sightread://p1/0,0,10,10)', '## Next section'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'fig', id: 'fig1', bbox: [0, 0, 10, 10], caption: null },
      { kind: 'h2', text: 'Next section', level: 2 },
    ])
  })

  it('keeps content that precedes the first marker as page 1', () => {
    const pages = parseResultMarkdown(['# Title', '<!-- page: 1 -->', 'Body.'].join('\n'))

    expect(pages).toHaveLength(1)
    expect(pages[0]!.page).toBe(1)
    expect(pages[0]!.blocks).toEqual([
      { kind: 'h2', text: 'Title', level: 1 },
      { kind: 'p', text: 'Body.' },
    ])
  })

  it('keeps the source heading depth on the two rendered kinds', () => {
    const pages = parseResultMarkdown(['<!-- page: 1 -->', '# Top', '#### Deep'].join('\n'))

    expect(pages[0]!.blocks).toEqual([
      { kind: 'h2', text: 'Top', level: 1 },
      { kind: 'h3', text: 'Deep', level: 4 },
    ])
  })

  it('returns nothing for an empty document', () => {
    expect(parseResultMarkdown('')).toEqual([])
  })
})

describe('formatBbox', () => {
  it('prints the four coordinates in the stored order', () => {
    expect(formatBbox([120, 60, 480, 940])).toBe('[120,60,480,940]')
  })
})

describe('parseResultMarkdown lists', () => {
  it('keeps an unordered list as its own block instead of merging it into a paragraph', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', 'Findings:', '', '- First', '- Second', '- Third'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'p', text: 'Findings:' },
      { kind: 'list', ordered: false, items: ['First', 'Second', 'Third'] },
    ])
  })

  it('reads an ordered list and its markers', () => {
    const pages = parseResultMarkdown(['<!-- page: 1 -->', '1. Alpha', '2) Beta'].join('\n'))

    expect(pages[0]!.blocks).toEqual([{ kind: 'list', ordered: true, items: ['Alpha', 'Beta'] }])
  })

  it('splits a bulleted list that follows a numbered one into two blocks', () => {
    const pages = parseResultMarkdown(['<!-- page: 1 -->', '1. Alpha', '- Beta'].join('\n'))

    expect(pages[0]!.blocks).toEqual([
      { kind: 'list', ordered: true, items: ['Alpha'] },
      { kind: 'list', ordered: false, items: ['Beta'] },
    ])
  })

  it('does not let a paragraph swallow the list that follows it', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', 'The regions were:', '- APAC', 'Totals follow.'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'p', text: 'The regions were:' },
      { kind: 'list', ordered: false, items: ['APAC'] },
      { kind: 'p', text: 'Totals follow.' },
    ])
  })
})

describe('parseResultMarkdown tables', () => {
  it('reads a GFM table whose rows omit the outer pipes', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', 'Region | Revenue', '--- | ---', 'APAC | 1,204'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'table', header: ['Region', 'Revenue'], rows: [['APAC', '1,204']] },
    ])
  })

  it('does not let a paragraph swallow an unpiped table that follows it', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', 'By region:', 'Region | Revenue', '--- | ---', 'APAC | 1,204'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'p', text: 'By region:' },
      { kind: 'table', header: ['Region', 'Revenue'], rows: [['APAC', '1,204']] },
    ])
  })

  it('leaves a sentence containing a pipe as prose', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', 'Run `a | b` to pipe the output.', 'It prints nothing.'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'p', text: 'Run `a | b` to pipe the output. It prints nothing.' },
    ])
  })

  it('ends a table at the prose under it', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', '| A | B |', '| --- | --- |', '| 1 | 2 |', 'Totals are provisional.'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'table', header: ['A', 'B'], rows: [['1', '2']] },
      { kind: 'p', text: 'Totals are provisional.' },
    ])
  })
})

describe('parseResultMarkdown table edge cases', () => {
  it('leaves a formula that starts with a pipe as prose', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', '|x| = 3', '|y| = 4', 'Both hold for every n.'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([{ kind: 'p', text: '|x| = 3 |y| = 4 Both hold for every n.' }])
  })

  it('keeps an escaped pipe inside a cell instead of splitting on it', () => {
    const pages = parseResultMarkdown(
      [
        '<!-- page: 1 -->',
        '| Vendor | Region |',
        '| --- | --- |',
        '| ACME \\| Europe | EMEA |',
      ].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      {
        kind: 'table',
        header: ['Vendor', 'Region'],
        rows: [['ACME | Europe', 'EMEA']],
      },
    ])
  })
})

describe('parseResultMarkdown formulas and wrapped items', () => {
  it('keeps the line breaks inside a display-math fence', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', 'Then:', '$$', '\\begin{aligned}', 'E &= mc^2', '\\end{aligned}', '$$', 'as shown.'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'p', text: 'Then:' },
      { kind: 'math', text: '\\begin{aligned}\nE &= mc^2\n\\end{aligned}' },
      { kind: 'p', text: 'as shown.' },
    ])
  })

  it('does not run an unclosed fence past its page', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', '$$', 'E = mc^2', '<!-- page: 2 -->', 'Next page.'].join('\n'),
    )

    expect(pages).toHaveLength(2)
    expect(pages[1]!.blocks).toEqual([{ kind: 'p', text: 'Next page.' }])
  })

  it('folds an indented continuation into the item above it', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', '- First line', '  wrapped onto a second', '- Second'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'list', ordered: false, items: ['First line wrapped onto a second', 'Second'] },
    ])
  })

  it('ends the list at an unindented line', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', '- Only item', 'A new paragraph.'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'list', ordered: false, items: ['Only item'] },
      { kind: 'p', text: 'A new paragraph.' },
    ])
  })
})

describe('parseResultMarkdown code and numbering', () => {
  it('keeps a fenced code block whole, with its language', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', 'Example:', '```python', 'def f(x):', '    return x + 1', '```', 'Done.'].join('\n'),
    )

    expect(pages[0]!.blocks).toEqual([
      { kind: 'p', text: 'Example:' },
      { kind: 'code', text: 'def f(x):\n    return x + 1', lang: 'python' },
      { kind: 'p', text: 'Done.' },
    ])
  })

  it('does not run an unclosed code fence past its page', () => {
    const pages = parseResultMarkdown(
      ['<!-- page: 1 -->', '```', 'x = 1', '<!-- page: 2 -->', 'Next page.'].join('\n'),
    )

    expect(pages).toHaveLength(2)
    expect(pages[1]!.blocks).toEqual([{ kind: 'p', text: 'Next page.' }])
  })

  it('keeps the number an ordered list starts at', () => {
    const pages = parseResultMarkdown(['<!-- page: 2 -->', '5. Fifth', '6. Sixth'].join('\n'))

    expect(pages[0]!.blocks).toEqual([
      { kind: 'list', ordered: true, items: ['Fifth', 'Sixth'], start: 5 },
    ])
  })

  it('leaves a list starting at one without a start attribute', () => {
    const pages = parseResultMarkdown(['<!-- page: 1 -->', '1. First'].join('\n'))

    expect(pages[0]!.blocks).toEqual([{ kind: 'list', ordered: true, items: ['First'] }])
  })
})

describe('parseInline', () => {
  it('splits affiliation superscripts into math spans', () => {
    const segments = parseInline('Qingwen Bu$^{1,2}$, Yanting Yang$^2$')

    expect(segments).toEqual([
      { kind: 'text', text: 'Qingwen Bu' },
      { kind: 'math', tex: '^{1,2}' },
      { kind: 'text', text: ', Yanting Yang' },
      { kind: 'math', tex: '^2' },
    ])
  })

  it('does not mistake prices for a formula', () => {
    expect(parseInline('costs $5 and $6 total')).toEqual([
      { kind: 'text', text: 'costs $5 and $6 total' },
    ])
  })

  it('finds a formula after a rejected price on the same line', () => {
    const segments = parseInline('cost $5 and variable $x$')

    expect(segments).toEqual([
      { kind: 'text', text: 'cost $5 and variable ' },
      { kind: 'math', tex: 'x' },
    ])
  })

  it('hands plain text through as one segment', () => {
    expect(parseInline('no math here')).toEqual([{ kind: 'text', text: 'no math here' }])
    expect(parseInline('')).toEqual([{ kind: 'text', text: '' }])
  })

  it('renders strong emphasis with its source kept for copy', () => {
    expect(parseInline('**96.5**')).toEqual([
      { kind: 'strong', segments: [{ kind: 'text', text: '96.5' }], src: '**96.5**' },
    ])
  })

  it('renders <br> as a line break inside a table cell', () => {
    expect(parseInline('UniVLA<br>(Ours)')).toEqual([
      { kind: 'text', text: 'UniVLA' },
      { kind: 'br', src: '<br>' },
      { kind: 'text', text: '(Ours)' },
    ])
  })

  it('nests emphasis one inside the other', () => {
    expect(parseInline('_**Abstract**_')).toEqual([
      {
        kind: 'em',
        segments: [
          { kind: 'strong', segments: [{ kind: 'text', text: 'Abstract' }], src: '**Abstract**' },
        ],
        src: '_**Abstract**_',
      },
    ])
  })

  it('keeps mid-word underscores as text', () => {
    expect(parseInline('usage_log and a_b_c stay text')).toEqual([
      { kind: 'text', text: 'usage_log and a_b_c stay text' },
    ])
  })

  it('renders single-asterisk emphasis', () => {
    expect(parseInline('*A. Main Results*')).toEqual([
      { kind: 'em', segments: [{ kind: 'text', text: 'A. Main Results' }], src: '*A. Main Results*' },
    ])
  })

  it('closes each emphasis span at its own marker', () => {
    expect(parseInline('**a** and **b**')).toEqual([
      { kind: 'strong', segments: [{ kind: 'text', text: 'a' }], src: '**a**' },
      { kind: 'text', text: ' and ' },
      { kind: 'strong', segments: [{ kind: 'text', text: 'b' }], src: '**b**' },
    ])
  })

  it('renders an inline code span verbatim', () => {
    expect(parseInline('run `uv sync` first')).toEqual([
      { kind: 'text', text: 'run ' },
      { kind: 'code', text: 'uv sync', src: '`uv sync`' },
      { kind: 'text', text: ' first' },
    ])
  })

  it('leaves unpaired markers as literal text', () => {
    expect(parseInline('5 * 3 and a ** that never closes')).toEqual([
      { kind: 'text', text: '5 * 3 and a ** that never closes' },
    ])
  })

  it('treats non-ASCII letters as word characters around underscores', () => {
    expect(parseInline('caf\u00e9_value_name and \u6e2c\u8a66_\u8b8a\u6578_\u540d\u7a31 stay text')).toEqual([
      { kind: 'text', text: 'caf\u00e9_value_name and \u6e2c\u8a66_\u8b8a\u6578_\u540d\u7a31 stay text' },
    ])
  })

  it('still opens underscore emphasis off punctuation and spaces', () => {
    expect(parseInline('a _b_ c')).toEqual([
      { kind: 'text', text: 'a ' },
      { kind: 'em', segments: [{ kind: 'text', text: 'b' }], src: '_b_' },
      { kind: 'text', text: ' c' },
    ])
  })

  it('leaves backslash-escaped markers literal', () => {
    expect(parseInline('\\*literal\\*')).toEqual([{ kind: 'text', text: '\\*literal\\*' }])
    expect(parseInline('*a\\*')).toEqual([{ kind: 'text', text: '*a\\*' }])
  })

  it('reads a triple-asterisk run as em holding strong', () => {
    expect(parseInline('***text***')).toEqual([
      {
        kind: 'em',
        segments: [
          { kind: 'strong', segments: [{ kind: 'text', text: 'text' }], src: '**text**' },
        ],
        src: '***text***',
      },
    ])
  })

  it('nests strong inside single-asterisk emphasis', () => {
    expect(parseInline('*outer **inner** text*')).toEqual([
      {
        kind: 'em',
        segments: [
          { kind: 'text', text: 'outer ' },
          { kind: 'strong', segments: [{ kind: 'text', text: 'inner' }], src: '**inner**' },
          { kind: 'text', text: ' text' },
        ],
        src: '*outer **inner** text*',
      },
    ])
  })

  it('nests em inside strong', () => {
    expect(parseInline('**a *b* c**')).toEqual([
      {
        kind: 'strong',
        segments: [
          { kind: 'text', text: 'a ' },
          { kind: 'em', segments: [{ kind: 'text', text: 'b' }], src: '*b*' },
          { kind: 'text', text: ' c' },
        ],
        src: '**a *b* c**',
      },
    ])
  })

  it('does not let a marker inside nested code close the emphasis', () => {
    expect(parseInline('*use `a*b` now*')).toEqual([
      {
        kind: 'em',
        segments: [
          { kind: 'text', text: 'use ' },
          { kind: 'code', text: 'a*b', src: '`a*b`' },
          { kind: 'text', text: ' now' },
        ],
        src: '*use `a*b` now*',
      },
    ])
    expect(parseInline('**use `a**b` now**')).toEqual([
      {
        kind: 'strong',
        segments: [
          { kind: 'text', text: 'use ' },
          { kind: 'code', text: 'a**b', src: '`a**b`' },
          { kind: 'text', text: ' now' },
        ],
        src: '**use `a**b` now**',
      },
    ])
  })

  it('keeps dollars inside a code span as code, not math', () => {
    expect(parseInline('write `$x$` literally')).toEqual([
      { kind: 'text', text: 'write ' },
      { kind: 'code', text: '$x$', src: '`$x$`' },
      { kind: 'text', text: ' literally' },
    ])
  })

  it('lets an escaped backtick protect nothing', () => {
    expect(parseInline('show \\` then $x$ and `code`')).toEqual([
      { kind: 'text', text: 'show \\` then ' },
      { kind: 'math', tex: 'x' },
      { kind: 'text', text: ' and ' },
      { kind: 'code', text: 'code', src: '`code`' },
    ])
  })

  it('lets an unclosed backtick protect nothing', () => {
    expect(parseInline('a ` b $x$')).toEqual([
      { kind: 'text', text: 'a ` b ' },
      { kind: 'math', tex: 'x' },
    ])
  })

  it('keeps underscores inside a math span out of emphasis', () => {
    expect(parseInline('$a_{1}$ and $b_{2}$')).toEqual([
      { kind: 'math', tex: 'a_{1}' },
      { kind: 'text', text: ' and ' },
      { kind: 'math', tex: 'b_{2}' },
    ])
  })
})
