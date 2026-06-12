import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
      "/v1": process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8000",
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (
            id.includes("react") ||
            id.includes("scheduler") ||
            id.includes("use-sync-external-store")
          ) {
            return "vendor-react";
          }
          if (id.includes("@tanstack") || id.includes("axios")) {
            return "vendor-data";
          }
          if (id.includes("radix-ui") || id.includes("lucide-react")) {
            return "vendor-ui";
          }
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    exclude: ["tests/e2e/**", "node_modules/**", "dist/**"],
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
