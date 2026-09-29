import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const devPort = Number(process.env.VITE_PORT ?? 5177)


// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    open: true,
    proxy: { "/api": "http://127.0.0.1:8001", "/health": "http://127.0.0.1:8001" },
    host: true,
    port: devPort,
  },
})
