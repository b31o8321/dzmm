import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '', '')
  return {
    plugins: [vue()],
    server: {
      host: '127.0.0.1',
      port: 5182,
      strictPort: true,
      proxy: {
        '/api': {
          target: env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8765',
          changeOrigin: true,
        },
      },
    },
  }
})
