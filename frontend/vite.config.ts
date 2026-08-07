import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const devPort = Number(process.env.VITE_PORT ?? 5174)
const devHost = process.env.VITE_HOST ?? '127.0.0.1'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: devHost,
    port: devPort,
  },
})
