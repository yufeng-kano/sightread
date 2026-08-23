import { describe, expect, it } from 'vitest'
import { formatBbox, parseResultMarkdown } from './markdown'

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
      { kind: 'h2', text: 'Quarterly results' },
      { kind: 'p', text: 'Revenue grew across every region, led by APAC.' },
    ])
    expect(pages[1]!.blocks).toEqual([
      { kind: 'h3', text: 'Notes' },
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
      { kind: 'h2', text: 'Next section' },
    ])
  })

  it('keeps content that precedes the first marker as page 1', () => {
    const pages = parseResultMarkdown(['# Title', '<!-- page: 1 -->', 'Body.'].join('\n'))

    expect(pages).toHaveLength(1)
    expect(pages[0]!.page).toBe(1)
    expect(pages[0]!.blocks).toEqual([
      { kind: 'h2', text: 'Title' },
      { kind: 'p', text: 'Body.' },
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
