import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const env = loadEnv(mode, repoRoot, '')
  return {
    plugins: [react()],
    envDir: repoRoot,
    server: {
      proxy: {
        '/api': {
          target: env.VITE_BACKEND_URL || 'http://127.0.0.1:5000',
          changeOrigin: true,
        },
      },
    },
  }
})
