import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite reads `.env` from the *frontend* folder by default. Our single source of
// truth is the repository-root `.env`, so `envDir` points one level up. Only
// variables prefixed with VITE_ are exposed to client code — that prefix is
// what stops the JWT secret and database password leaking into the bundle.
export default defineConfig({
  plugins: [react()],
  envDir: '..',
  server: {
    port: 5173,
    // Fail loudly instead of silently moving to :5174, which would break CORS
    // and the WebSocket origin checks configured on the backend.
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  // The MediaPipe WASM runtime is served as a static asset from public/models.
  // Excluding it from dependency pre-bundling stops Vite trying to parse the
  // .wasm binaries as JavaScript modules.
  optimizeDeps: {
    exclude: ['@mediapipe/tasks-vision'],
  },
});
