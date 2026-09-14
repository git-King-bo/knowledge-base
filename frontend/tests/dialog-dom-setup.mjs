import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true })
for (const key of ['window', 'document', 'Element', 'HTMLElement', 'SVGElement', 'HTMLInputElement', 'HTMLTextAreaElement', 'HTMLSelectElement', 'HTMLCanvasElement', 'HTMLDialogElement', 'Event', 'MouseEvent', 'getComputedStyle']) globalThis[key] = dom.window[key]
Object.assign(globalThis, { innerWidth: 1200, innerHeight: 900, devicePixelRatio: 1 })
dom.window.CSSStyleDeclaration.prototype[Symbol.iterator] = function* () { for (let i = 0; i < this.length; i++) yield this[i] }
HTMLDialogElement.prototype.showModal = function () { this.open = true }
HTMLDialogElement.prototype.close = function () { this.open = false }
HTMLElement.prototype.getBoundingClientRect = function () { return { left: 300, top: 180, width: 500, height: 540 } }
HTMLElement.prototype.getClientRects = function () { return this.isConnected ? [{}] : [] }
const calls = []
globalThis.dialogDraws = calls
HTMLCanvasElement.prototype.getContext = function () { return { canvas: this, scale() {}, clearRect() {}, drawImage(...args) { calls.push(args.slice(1)) } } }
let id = 0
const frames = new Map()
globalThis.requestAnimationFrame = cb => { frames.set(++id, cb); return id }
globalThis.cancelAnimationFrame = key => frames.delete(key)
globalThis.dialogFrames = frames
globalThis.advanceDialogFrame = time => { const pending = [...frames.values()]; frames.clear(); pending.forEach(cb => cb(time)) }
const listeners = new Set()
const media = { matches: false, addEventListener: (_, cb) => listeners.add(cb), removeEventListener: (_, cb) => listeners.delete(cb) }
globalThis.matchMedia = () => media
globalThis.setDialogReducedMotion = value => { media.matches = value; listeners.forEach(cb => cb()) }
