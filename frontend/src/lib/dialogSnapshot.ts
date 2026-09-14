import { toCanvas } from 'html-to-image'

/** Clone only for rasterization; never move or replace the live form nodes. */
export function captureDialog(panel: HTMLElement) {
  const clone = panel.cloneNode(true) as HTMLElement
  const originals = [panel, ...panel.querySelectorAll<HTMLElement>('*')]
  const copies = [clone, ...clone.querySelectorAll<HTMLElement>('*')]
  originals.forEach((node, index) => {
    const copy = copies[index]!
    const style = getComputedStyle(node)
    for (const key of style) copy.style.setProperty(key, style.getPropertyValue(key))
    copy.removeAttribute('id')
    if (node instanceof HTMLInputElement && copy instanceof HTMLInputElement) {
      copy.value = node.type === 'password' ? '•'.repeat(node.value.length) : node.value
      if (node.type === 'password') copy.type = 'text'
      copy.checked = node.checked
      if (node.checked) copy.setAttribute('checked', '')
      else copy.removeAttribute('checked')
    }
    if (node instanceof HTMLTextAreaElement && copy instanceof HTMLTextAreaElement) copy.textContent = node.value
    if (node instanceof HTMLSelectElement && copy instanceof HTMLSelectElement) copy.selectedIndex = node.selectedIndex
    if (node instanceof HTMLCanvasElement && copy instanceof HTMLCanvasElement) copy.getContext('2d')?.drawImage(node, 0, 0)
  })
  // SVG foreignObject does not serialize scroll offsets. Translate cloned contents
  // inside the original overflow viewport, including the root scrolling panel.
  originals.forEach((node, index) => {
    if ((!node.scrollTop && !node.scrollLeft) || /^(INPUT|SELECT)$/.test(node.tagName)) return
    if (node instanceof HTMLTextAreaElement) {
      const copy = copies[index]!
      const viewport = document.createElement('div')
      viewport.style.cssText = copy.style.cssText
      viewport.style.overflow = 'hidden'
      const text = document.createElement('div')
      text.style.cssText = `white-space:pre-wrap;overflow-wrap:break-word;transform:translate(${-node.scrollLeft}px,${-node.scrollTop}px)`
      text.textContent = node.value
      viewport.append(text); copy.replaceWith(viewport)
      return
    }
    const copy = copies[index]!
    const inner = document.createElement('div')
    inner.style.cssText = `width:${node.scrollWidth - parseFloat(getComputedStyle(node).paddingLeft) - parseFloat(getComputedStyle(node).paddingRight)}px;transform:translate(${-node.scrollLeft}px,${-node.scrollTop}px)`
    inner.append(...copy.childNodes)
    copy.append(inner)
    copy.style.overflow = 'hidden'
  })
  const rect = panel.getBoundingClientRect()
  Object.assign(clone.style, { opacity: '1', visibility: 'visible', margin: '0', position: 'relative', width: `${rect.width}px`, height: `${rect.height}px`, maxHeight: 'none', maxWidth: 'none', boxSizing: 'border-box' })
  const host = document.createElement('div')
  host.setAttribute('aria-hidden', 'true')
  host.dataset.macDialogSnapshot = ''
  host.inert = true
  host.style.cssText = 'position:fixed;left:0;top:0;opacity:0;pointer-events:none;z-index:-1'
  host.append(clone)
  document.body.append(host)
  const promise = toCanvas(clone, { width: rect.width, height: rect.height, pixelRatio: Math.min(devicePixelRatio || 1, 2) })
  return { promise, dispose: () => host.remove() }
}
