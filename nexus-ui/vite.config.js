import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy target — defaults to the docker-compose.prod.yml host bind
// (127.0.0.1:8210). Override per-developer with VITE_API_TARGET in
// .env.local (e.g. http://127.0.0.1:8000 for base docker-compose.yml,
// or http://127.0.0.1:8501 against the legacy v1 systemd unit if it
// ever comes back up for debugging).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = 'https://chat.nexus.gayo-sphere.cloud';

  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          secure: false,
          // SSE keepalive: identity encoding prevents gzip-buffering
          // of /api/chat/stream so tokens render as they arrive.
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              proxyReq.setHeader('Accept-Encoding', 'identity');
            });
          },
        },
        '/webhook': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: true,
    },
  };
});
