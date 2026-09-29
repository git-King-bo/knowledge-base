import { build } from 'vite'
import vue from '@vitejs/plugin-vue'
import { spawnSync } from 'node:child_process'
import { readdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
const path = value => fileURLToPath(new URL(value, import.meta.url))
const files = (await readdir(path('./'))).filter(name => name.endsWith('.test.ts')).sort()
let failed = false
for (const file of files) {
  const name = file.replace('.ts', '.mjs')
  const output = path(`../node_modules/.cache/all-tests/${file}/`)
  await build({ configFile: false, plugins: [vue()], logLevel: 'warn',
    resolve: { alias: { 'html-to-image': path('./dialog-image-mock.ts') } },
    build: { lib: { entry: path('./' + file), formats: ['es'], fileName: () => name },
      outDir: output, emptyOutDir: true, minify: false,
      rollupOptions: { external: ['vue', 'node:test', 'node:assert/strict'] } },
  })
  const result = spawnSync(process.execPath, ['--import', path('./dialog-dom-setup.mjs'), '--test', `${output}/${name}`], { stdio: 'inherit' })
  if (result.status !== 0) failed = true
}
process.exit(failed ? 1 : 0)
