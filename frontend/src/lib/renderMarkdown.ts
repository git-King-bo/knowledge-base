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
import { Marked, Renderer } from 'marked'
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

export function escapeHtml(value: string) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

export function safeExternalUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined
  } catch { return undefined }
}

interface RenderMarkdownOptions {
  sourceRefs?: boolean
  streaming?: boolean
}

function createRenderer(highlight: boolean) {
  let references = false
  let tones = new Map<string, number>()
  const parser = new Marked({ async: false, breaks: true, gfm: true })
  parser.use({ renderer: {
    // Raw model HTML is text: it cannot create controls or forge citation buttons.
    html({ text }) { return escapeHtml(text) },
    text(token) {
      const html = Renderer.prototype.text.call(this, token) as string
      if (!references) return html
      return html.replace(/[\(（\[]\s*((?:(?:Chunk|Source|Web)\s+\d+\s*(?:[,，]\s*)?)+)\s*[\)）\]]/gi, (_, refs: string) => {
        const buttons = [...refs.matchAll(/(Chunk|Source|Web)\s+(\d+)/gi)].map(match => {
          const kind = match[1]!.toLowerCase() === 'web' ? 'web' : 'chunk'
          const number = Number(match[2])
          if (!Number.isSafeInteger(number)) return ''
          const key = `${kind}:${number}`
          if (!tones.has(key)) tones.set(key, tones.size % 12)
          const title = `${kind === 'web' ? 'Web' : 'Chunk'} ${number}`
          return `<button class="source-inline-ref ${kind === 'web' ? 'web-ref' : ''} ref-tone-${tones.get(key)}" type="button" data-${kind}-ref="${number}" title="${title}" aria-label="${title}">${kind === 'web' ? 'W' : ''}${number}</button>`
        }).join('')
        return `<span class="source-inline-refs" aria-label="引用来源">${buttons}</span>`
      })
    },
    link({ href, title, tokens }) {
      const label = this.parser.parseInline(tokens)
      const url = safeExternalUrl(href)
      return url ? `<a href="${escapeHtml(url)}" title="${escapeHtml(title || '')}" target="_blank" rel="noopener noreferrer">${label}</a>` : label
    },
    image({ href, text }) {
      const url = safeExternalUrl(href)
      const label = escapeHtml(text || '图片')
      return url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">[图片：${label}]</a>` : label
    },
  } })
  if (highlight) parser.use(markedHighlight({
    emptyLangClass: 'hljs', langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    },
  }))
  return (source: string, options: RenderMarkdownOptions) => {
    references = options.sourceRefs ?? false
    tones = new Map()
    return parser.parse(source, { async: false }) as string
  }
}

const renderFinal = createRenderer(true)
const renderStreaming = createRenderer(false)

export function renderMarkdown(source: string, options: RenderMarkdownOptions = {}) {
  // Parse a full snapshot, never append HTML fragments. Marked closes code blocks;
  // incomplete emphasis and links remain text until the delimiters arrive.
  const text = (source || '').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
  const html = (options.streaming ? renderStreaming : renderFinal)(text, options)
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'b',
      'em', 'i', 'del', 's', 'blockquote', 'ul', 'ol', 'li', 'pre', 'code', 'table',
      'thead', 'tbody', 'tr', 'th', 'td', 'a', 'span', 'button', 'input'],
    ALLOWED_ATTR: ['class', 'href', 'title', 'target', 'rel', 'type', 'disabled', 'checked',
      'start', 'align', 'aria-label', 'data-chunk-ref', 'data-web-ref'],
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false,
    ADD_URI_SAFE_ATTR: ['data-chunk-ref', 'data-web-ref', 'aria-label', 'target', 'rel'],
    ALLOWED_URI_REGEXP: /^https?:\/\//i,
    SANITIZE_NAMED_PROPS: true,
  })
}
