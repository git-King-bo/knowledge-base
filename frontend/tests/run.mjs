import { build } from 'vite'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
const output = fileURLToPath(new URL('../node_modules/.cache/workspace-tests/', import.meta.url))
await build({
  configFile: false,
  logLevel: 'warn',
  build: {
    ssr: fileURLToPath(new URL('./streaming.test.ts', import.meta.url)),
    outDir: output,
    emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: 'streaming.test.mjs' } },
  },
})
const setup = fileURLToPath(new URL('./dom-setup.mjs', import.meta.url))
const result = spawnSync(process.execPath, ['--import', setup, '--test', `${output}/streaming.test.mjs`], { stdio: 'inherit' })
process.exit(result.status ?? 1)
