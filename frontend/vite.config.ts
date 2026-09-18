import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const devPort = Number(process.env.VITE_PORT ?? 5174)


// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    open: true,
    host: true,
    port: devPort,
  },
})
