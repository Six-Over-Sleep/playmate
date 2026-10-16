import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 기존 envDir: '..'와 같은 저장소 루트를 실행 위치에 관계없이 사용한다.
const envDir = fileURLToPath(new URL('../', import.meta.url))

export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, envDir, '')
  const target = (env.BACKEND_PROXY_TARGET || '').trim()

  if (command === 'serve' && !target) {
    throw new Error('프로젝트 루트 .env에 BACKEND_PROXY_TARGET을 설정해주세요. .env.example을 참고하세요.')
  }

  return {
    plugins: [react()],
    envDir,
    server: {
      port: 5173,
      proxy: target ? {
        '/api': { target, changeOrigin: true },
        '/auth': { target, changeOrigin: true },
        '/uploads': { target, changeOrigin: true },
      } : undefined,
    },
  }
})
