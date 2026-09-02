import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Agent 跑在 https://127.0.0.1:5179，用自簽憑證。
// 這裡走 Vite proxy：瀏覽器只跟 Vite 同源溝通，轉發在 Node 端完成。
// 效果：沒有 CORS、沒有憑證警告、port 可自由選。
// 改 agent port 只需要動下面這一行。
const AGENT_ORIGIN = 'https://127.0.0.1:5179'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      '/api': {
        target: AGENT_ORIGIN,
        changeOrigin: true,
        secure: false, // 忽略自簽憑證
      },
    },
  },
})
