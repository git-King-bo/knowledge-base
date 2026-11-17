/** UUID v4 for both HTTPS and the deployed HTTP site. Never fall back to Math.random. */
export function createId(): string {
  const provider = globalThis.crypto
  if (typeof provider?.randomUUID === 'function') return provider.randomUUID()
  if (typeof provider?.getRandomValues !== 'function') throw new Error('当前浏览器不支持安全随机数，请更换浏览器')
  const bytes = provider.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`
}
