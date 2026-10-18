import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In emulator mode the dashboard calls the API on the same origin; during
// `npm run dev` these paths are forwarded to the emulator on port 8000.
const API_PATHS = ['/me', '/overview', '/events', '/incidents', '/pipeline', '/rules', '/simulator', '/admin']
const target = process.env.CLOUDLOG_API || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  // three.js (the 3D pipeline model) is ~590 kB on its own; it is lazy-loaded, never in the first page load.
  build: { chunkSizeWarningLimit: 650 },
  server: {
    proxy: Object.fromEntries(API_PATHS.map((p) => [p, { target, changeOrigin: true }])),
  },
})
