import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/simulate": "http://127.0.0.1:8000",
      "/lineups": "http://127.0.0.1:8000"
    }
  }
});
