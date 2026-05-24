import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({

  plugins: [react()],
  server: {
    allowedHosts: ["e-mall.site", "e-mall.store", "feed.e-mall.site", "feed.e-mall.store"],
    host: "127.0.0.1",
    port: 5173,
  },
});

