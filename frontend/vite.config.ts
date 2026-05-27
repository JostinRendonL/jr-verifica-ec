import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // En dev, las llamadas /api/* van al backend FastAPI
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
      // Endpoints que no tienen prefijo /api en FastAPI
      '/historial': { target: 'http://localhost:8000', changeOrigin: true },
      '/consulta':  { target: 'http://localhost:8000', changeOrigin: true },
      '/lote':      { target: 'http://localhost:8000', changeOrigin: true },
      '/login':     { target: 'http://localhost:8000', changeOrigin: true },
      '/logout':    { target: 'http://localhost:8000', changeOrigin: true },
      '/usuarios':  { target: 'http://localhost:8000', changeOrigin: true },
      '/metrics':   { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: '../src/static/frontend',
    emptyOutDir: true,
  },
})
