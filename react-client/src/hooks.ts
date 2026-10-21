import { useEffect, useState } from 'react';
import type { dh as DhType } from '@deephaven/jsapi-types';
import { useApi } from '@deephaven/jsapi-bootstrap';
import { useConnection } from '@deephaven/app-utils';

export type Row = Record<string, unknown>;

/** Unwrap JS API value wrappers (LongWrapper, BigDecimal, DateWrapper) into plain JS. */
function toJs(value: unknown): unknown {
  if (value != null && typeof value === 'object') {
    const v = value as { asNumber?: () => number; asDate?: () => Date };
    if (typeof v.asNumber === 'function') return v.asNumber();
    if (typeof v.asDate === 'function') return v.asDate();
  }
  return value;
}

/**
 * Fetch a server-side table by its global variable name. Each call gets its
 * own handle (and therefore its own viewport); closed on unmount.
 */
export function useNamedTable(name: string): { table?: DhType.Table; error?: string } {
  const dh = useApi();
  const connection = useConnection();
  const [state, setState] = useState<{ table?: DhType.Table; error?: string }>({});

  useEffect(() => {
    let table: DhType.Table | undefined;
    let cancelled = false;
    connection
      .getObject({ type: dh.VariableType.TABLE, name })
      .then((t: DhType.Table) => {
        if (cancelled) t.close();
        else setState({ table: (table = t) });
      })
      .catch((e: unknown) => setState({ error: `${e}` }));
    return () => {
      cancelled = true;
      table?.close();
    };
  }, [dh, connection, name]);

  return state;
}

/**
 * Subscribe to the first `maxRows` rows of a (ticking) table and expose them as
 * plain objects. This is the low-level JS API path: set a viewport, then listen
 * for EVENT_UPDATED, which fires on every server tick that touches the viewport.
 */
export function useViewportRows(table: DhType.Table | undefined, maxRows = 50): Row[] {
  const dh = useApi();
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    if (table == null) return undefined;
    table.setViewport(0, maxRows - 1);
    const removeListener = table.addEventListener<DhType.ViewportData>(
      dh.Table.EVENT_UPDATED,
      event => {
        const { rows: vpRows, columns } = event.detail;
        setRows(
          vpRows.map(r => Object.fromEntries(columns.map(c => [c.name, toJs(r.get(c))])))
        );
      }
    );
    return removeListener;
  }, [dh, table, maxRows]);

  return rows;
}

/** One console session per browser tab, used to invoke server-side Python "callbacks". */
export function useIdeSession(): DhType.IdeSession | undefined {
  const connection = useConnection();
  const [session, setSession] = useState<DhType.IdeSession>();
  useEffect(() => {
    let s: DhType.IdeSession | undefined;
    connection.startSession('python').then(x => setSession((s = x)));
    return () => s?.close();
  }, [connection]);
  return session;
}

export const money = (x: unknown): string =>
  typeof x === 'number'
    ? x.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : '–';
