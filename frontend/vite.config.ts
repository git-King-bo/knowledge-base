import { defineConfig, type ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'
import { randomUUID } from 'node:crypto'

const devPort = Number(process.env.VITE_PORT ?? 5177)


// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const online = command === 'serve' && mode === 'online'
  const target = online ? 'http://future.ops.originhub.tech' : 'http://127.0.0.1:8001'
  const proxy: ProxyOptions = online ? {
    target,
    changeOrigin: true,
    cookieDomainRewrite: '',
    // Only the loopback development proxy rewrites Origin; production CSRF stays enabled.
    headers: { Origin: target },
  } : { target }
  if (online) console.info('[online] 本地前端连接线上后端：操作使用线上账号和数据。')
  const version = command === 'build' ? (process.env.VITE_APP_VERSION || randomUUID()) : 'development'
  return {
  define: { __APP_VERSION__: JSON.stringify(version), ...(online ? { 'import.meta.env.VITE_API_BASE_URL': JSON.stringify('/api') } : {}) },
  plugins: [vue(), { name: 'release-version', generateBundle() {
    this.emitFile({ type: 'asset', fileName: 'version.json', source: JSON.stringify({ version }) })
  } }],
  server: {
    open: true,
    proxy: { "/api": proxy, "/health": proxy, "/ready": proxy },
    host: online ? '127.0.0.1' : true,
    port: devPort,
  },
}
})
