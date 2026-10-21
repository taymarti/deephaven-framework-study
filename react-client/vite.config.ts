import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

// This Vite server is the "separate standalone web server" for approach (2).
// It serves OUR compiled React bundle on :4010 and reverse-proxies the few
// paths the Deephaven JS API needs to the Deephaven server on :10000, so the
// browser talks to a single origin (no CORS, one port to expose).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.VITE_PROXY_URL || 'http://localhost:10000';
  const proxy = {
    '/jsapi': { target, changeOrigin: true }, // dh-core.js (the JS API itself)
    '/js-plugins': { target, changeOrigin: true }, // server-side JS plugin manifest
    // gRPC-web / websocket traffic made by the JS API client
    '^/arrow\\..*': { target, changeOrigin: true, ws: true },
    '^/io\\.deephaven\\..*': { target, changeOrigin: true, ws: true },
  };
  return {
    server: { port: 4010, proxy },
    preview: { port: 4010, proxy },
    resolve: {
      dedupe: ['react', 'react-dom', 'react-redux', 'redux'],
      alias: [
        // CJS/ESM default-export interop fix; see the shim for details.
        {
          find: /^@paciolan\/remote-module-loader$/,
          replacement: fileURLToPath(new URL('./src/shims/remote-module-loader.ts', import.meta.url)),
        },
      ],
    },
    define: { 'process.env': {} },
    optimizeDeps: { esbuildOptions: { define: { global: 'globalThis' } } },
    plugins: [react()],
  };
});
