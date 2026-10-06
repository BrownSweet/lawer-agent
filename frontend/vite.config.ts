import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig(({ command, mode, isPreview }) => ({
  base: loadEnv(mode, '.', 'VITE_').VITE_BASE_PATH || (command === 'build' || isPreview ? '/lawer/' : '/'),
  plugins: [vue()],
  server: { proxy: { '/api': 'http://127.0.0.1:8891' } },
}))
