import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    host: true,
    allowedHosts: [
      "hesperidate-unrestrainedly-wai.ngrok-free.dev",
      ".ngrok-free.dev",
      ".ngrok.app",
      ".ngrok.io",
      "localhost",
      "127.0.0.1",
    ],
    proxy: {
      "/api": "http://127.0.0.1:8001",
      "/ws": { target: "ws://127.0.0.1:8001", ws: true },
    },
  },
});
