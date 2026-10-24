/**
 * The Deephaven connection, with no @deephaven React packages: the JS API module is served by the
 * Deephaven server itself (/jsapi/dh-core.js, proxied same-origin by dh-desk-web), so the client
 * always matches the server's version. Types come from @deephaven/jsapi-types (dev only).
 */
import type { dh as Dh } from '@deephaven/jsapi-types';

export type DhApi = typeof Dh;
export type Table = Dh.Table;
export type Row = Record<string, unknown>;

export interface Deephaven {
  dh: DhApi;
  connection: Dh.IdeConnection;
}

async function connect(): Promise<Deephaven> {
  const origin = window.location.origin;
  const mod = await import(/* @vite-ignore */ `${origin}/jsapi/dh-core.js`);
  const dh: DhApi = mod.default;
  const client = new dh.CoreClient(origin);
  await client.login({ type: dh.CoreClient.LOGIN_TYPE_ANONYMOUS });
  const connection = await client.getAsIdeConnection();
  return { dh, connection };
}

/** One connection per page; React components read it with use(deephaven). */
export const deephaven: Promise<Deephaven> = connect();

const tables = new Map<string, Promise<Table>>();

/** A handle to a published table by name (the server's console scope), cached per name. */
export function tablePromise(name: string): Promise<Table> {
  let p = tables.get(name);
  if (p === undefined) {
    p = deephaven.then(({ dh, connection }) => connection.getObject({ type: dh.VariableType.TABLE, name }) as Promise<Table>);
    tables.set(name, p);
  }
  return p;
}

/** Unwrap JS API value wrappers (LongWrapper, DateWrapper, BigDecimal) into plain JS values. */
export function toJs(value: unknown): unknown {
  if (value != null && typeof value === 'object') {
    const v = value as { asNumber?: () => number; asDate?: () => Date };
    if (typeof v.asNumber === 'function') return v.asNumber();
    if (typeof v.asDate === 'function') return v.asDate();
  }
  return value;
}
