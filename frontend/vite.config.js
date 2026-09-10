import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Everything is inlined into a single JS/CSS pair at build time: the runtime
// container is plain nginx serving static files, and the page never requests a
// font, script or stylesheet from anywhere but itself.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    assetsInlineLimit: 4096,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.[hash].js",
        chunkFileNames: "assets/[name].[hash].js",
        assetFileNames: "assets/[name].[hash][extname]",
      },
    },
  },
  server: {
    port: 3000,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
