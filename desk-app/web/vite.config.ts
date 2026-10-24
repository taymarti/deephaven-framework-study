import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Web build unit: a standard Vite app (index.html, src/) whose build lands in dist/, which the
// Python wheel bundles as package data. `npm run dev` serves on :4010 and proxies Deephaven's JS API
// to dh-desk-server, exactly as `dh-desk-web` does in production, so the app always talks to one origin.
const target = process.env.DH_URL ?? 'http://localhost:10000';
const proxy = Object.fromEntries(
  ['/jsapi', '/js-plugins', '^/arrow\..*', '^/io\.deephaven\..*'].map(p => [p, { target, changeOrigin: true, ws: true }])
);

export default defineConfig({
  plugins: [react()],
  server: { port: 4010, proxy },
  build: { target: 'es2022' },
});
