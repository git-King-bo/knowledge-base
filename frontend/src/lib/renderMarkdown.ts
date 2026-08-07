import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import plaintext from 'highlight.js/lib/languages/plaintext'
import python from 'highlight.js/lib/languages/python'
import shell from 'highlight.js/lib/languages/shell'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import 'highlight.js/styles/github-dark.css'
import { marked } from 'marked'
import { markedHighlight } from 'marked-highlight'

hljs.registerLanguage('bash', bash)
hljs.registerLanguage('css', css)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('md', markdown)
hljs.registerLanguage('plaintext', plaintext)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('shell', shell)
hljs.registerLanguage('sh', shell)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('yml', yaml)

marked.use(
  markedHighlight({
    emptyLangClass: 'hljs',
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    },
  }),
)

marked.setOptions({
  async: false,
  breaks: true,
  gfm: true,
})

interface RenderMarkdownOptions {
  sourceRefs?: boolean
}

function renderSourceRefs(source: string) {
  const toneByNumber = new Map<number, number>()
  for (const match of source.matchAll(/(?:Chunk|Source)\s+(\d+)/gi)) {
    const number = Number(match[1])
    if (!toneByNumber.has(number)) {
      toneByNumber.set(number, toneByNumber.size % 12)
    }
  }

  return source.replace(/[\(（]\s*((?:(?:Chunk|Source)\s+\d+\s*(?:[,，]\s*)?)+)\s*[\)）]/gi, (_, refs: string) => {
    const numbers = [...refs.matchAll(/(?:Chunk|Source)\s+(\d+)/gi)].map((match) => Number(match[1]))
    if (!numbers.length) return _
    const buttons = numbers
      .map(
        (number) => {
          const tone = toneByNumber.get(number) ?? 0
          return `<button class="source-inline-ref ref-tone-${tone}" type="button" data-chunk-ref="${number}" title="Chunk ${number}" aria-label="切片 ${number}">${number}</button>`
        },
      )
      .join('')
    return `<span class="source-inline-refs" aria-label="引用切片">${buttons}</span>`
  })
}

export function renderMarkdown(source: string, options: RenderMarkdownOptions = {}) {
  const nextSource = options.sourceRefs ? renderSourceRefs(source || '') : source || ''
  const html = marked.parse(nextSource, { async: false }) as string
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target', 'rel', 'type', 'title', 'aria-label', 'data-chunk-ref'],
  })
}
