import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  // Production build is served under /dashboard by backend/main.py's
  // StaticFiles mount; dev server stays at root so the proxy setup below
  // keeps working unchanged.
  base: command === "build" ? "/dashboard/" : "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
}));
