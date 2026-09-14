/** Batch text and its final render into at most one scheduled render per animation frame. */
export function createFrameBuffer(render: (text: string, final: boolean) => void) {
  let text = ''
  let frame: number | undefined
  let final = false
  let disposed = false
  let finishResolve: (() => void) | undefined
  const finished = new Promise<void>(resolve => { finishResolve = resolve })
  function schedule() {
    if (disposed || frame !== undefined) return
    frame = requestAnimationFrame(() => {
      frame = undefined
      if (disposed) return
      try { render(text, final) }
      finally { if (final) finishResolve?.() }
    })
  }
  return {
    append(delta: string) {
      if (disposed || final) return
      text += delta
      schedule()
    },
    finish() {
      if (disposed) return Promise.resolve()
      final = true
      schedule()
      return finished
    },
    dispose() {
      disposed = true
      if (frame !== undefined) cancelAnimationFrame(frame)
      frame = undefined
      finishResolve?.()
    },
  }
}
