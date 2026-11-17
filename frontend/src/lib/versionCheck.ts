export function createVersionChecker(current: string, notify: (version: string) => void,
  fetcher: typeof fetch = fetch) {
  let checking = false
  let stopped = false
  let controller: AbortController | undefined
  return {
    async check() {
      if (checking || stopped) return
      checking = true
      controller = new AbortController()
      const timeout = setTimeout(() => controller?.abort(), 8000)
      try {
        const response = await fetcher('/version.json', { cache: 'no-store', signal: controller.signal })
        if (!response.ok) return
        const data: unknown = await response.json()
        if (!stopped && data && typeof data === 'object' && 'version' in data &&
          typeof data.version === 'string' && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$/.test(data.version)) notify(data.version === current ? '' : data.version)
      } catch { /* Offline, deployment windows and old servers do not imply an update. */ }
      finally { clearTimeout(timeout); checking = false }
    },
    stop() { stopped = true; controller?.abort() },
  }
}
