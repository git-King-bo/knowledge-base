export const captures: HTMLElement[] = []
export let mode: 'success' | 'failure' | 'pending' = 'success'
export function setMode(value: typeof mode) { mode = value }
export const waiting: Array<(canvas: HTMLCanvasElement) => void> = []
export function toCanvas(node: HTMLElement) {
  captures.push(node)
  if (mode === 'failure') return Promise.reject(new Error('snapshot failed'))
  if (mode === 'pending') return new Promise<HTMLCanvasElement>(resolve => waiting.push(resolve))
  const canvas = document.createElement('canvas'); canvas.width = 500; canvas.height = 540
  return Promise.resolve(canvas)
}
