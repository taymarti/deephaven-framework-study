// @deephaven/app-utils (an ESM package) does
//   import createLoadRemoteModule, { createRequires } from '@paciolan/remote-module-loader'
// but that dependency is CommonJS with `exports.default = fn`. Under Node-style
// ESM interop the default import becomes the whole exports object, so the call
// fails with "is not a function". This shim normalizes both shapes.
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - deep import has no separate typings entry
import * as mod from '@paciolan/remote-module-loader/dist/index.js';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const m = mod as any;
const root = m.default ?? m;

export const createRequires = m.createRequires ?? root.createRequires;
export const createLoadRemoteModule = root.default ?? root.createLoadRemoteModule ?? root;
export default createLoadRemoteModule;
