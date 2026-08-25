import { describe, expect, it } from 'vitest'
import { renderTexHtml } from './math'

describe('renderTexHtml', () => {
  it('typesets a cases environment in display mode', () => {
    const html = renderTexHtml('\\begin{cases} a & b \\\\ c & d \\end{cases}', true)

    expect(html).not.toBeNull()
    expect(html).toContain('katex-display')
  })

  it('typesets affiliation-grade inline math', () => {
    expect(renderTexHtml('^{1,2}', false)).toContain('katex')
  })

  it('covers the \\degree transcriptions produce', () => {
    expect(renderTexHtml('\\text{25}\\degree', false)).not.toBeNull()
  })

  it('returns null for TeX KaTeX cannot parse, so the caller keeps the source', () => {
    expect(renderTexHtml('\\frobnicate{x}', false)).toBeNull()
  })
})
