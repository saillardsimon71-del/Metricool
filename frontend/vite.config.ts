import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Le backend FastAPI local sert de proxy en développement : l'interface n'appelle
// jamais directement localhost:8000 depuis le navigateur (mêmes origines relatives).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
    allowedHosts: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 1200 },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
} as never)
