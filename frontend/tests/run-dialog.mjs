import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const path = value => fileURLToPath(new URL(value, import.meta.url))
const output = path('../node_modules/.cache/dialog-tests/')
await build({ configFile: false, plugins: [vue()], logLevel: 'warn',
  resolve: { alias: { 'html-to-image': path('./dialog-image-mock.ts') } },
  build: { lib: { entry: path('./mac-dialog.test.ts'), formats: ['es'], fileName: () => 'mac-dialog.test.mjs' }, outDir: output, emptyOutDir: true, minify: false,
    rollupOptions: { external: ['vue', 'node:test', 'node:assert/strict'] } },
})
const result = spawnSync(process.execPath, ['--import', path('./dialog-dom-setup.mjs'), '--test', `${output}/mac-dialog.test.mjs`], { stdio: 'inherit' })
process.exit(result.status ?? 1)
