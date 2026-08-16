import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: Number(process.env.DEV_PORT) || 3000,
    allowedHosts: true,
  },
})
