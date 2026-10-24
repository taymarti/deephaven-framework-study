import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Web build unit. Sources live in src/main/web (beside src/main/java and src/main/python);
// the build lands in target/web, which the Python wheel bundles as package data.
// `npm run dev` serves on :4010 and proxies Deephaven's JS API to dh-desk-server, exactly as
// `dh-desk-web` does in production, so the app always talks to one origin.
const target = process.env.DH_URL ?? 'http://localhost:10000';
const proxy = Object.fromEntries(
  ['/jsapi', '/js-plugins', '^/arrow\..*', '^/io\.deephaven\..*'].map(p => [p, { target, changeOrigin: true, ws: true }])
);

export default defineConfig({
  root: 'src/main/web',
  plugins: [react()],
  server: { port: 4010, proxy },
  build: { outDir: '../../../target/web', emptyOutDir: true, target: 'es2022', sourcemap: false },
});
