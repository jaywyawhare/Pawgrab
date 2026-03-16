import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: process.env.NODE_ENV === 'production' ? '/Pawgrab/' : '/',
  server: {
    port: 3000,
    open: true,
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'syntax-highlighter': ['react-syntax-highlighter'],
          'markdown': ['react-markdown', 'remark-gfm', 'rehype-raw', 'rehype-sanitize'],
          'animation': ['gsap', 'framer-motion'],
          'three': ['three'],
        },
      },
    },
  },
})
