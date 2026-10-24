import { use, useEffect, useState } from 'react';
import { deephaven, tablePromise, toJs, type Row, type Table } from './deephaven';

/** The table published as `name`; suspends until the handle is ready. */
export function useTable(name: string): Table {
  return use(tablePromise(name));
}

/**
 * Live rows of a (ticking) table: subscribe to a viewport of the first `maxRows` rows and
 * re-render on every server update that touches it (Barrage deltas, applied by the JS API).
 */
export function useLiveRows(table: Table, maxRows = 100): Row[] {
  const { dh } = use(deephaven);
  const [rows, setRows] = useState<Row[]>([]);
  useEffect(() => {
    const subscription = table.setViewport(0, maxRows - 1);
    const remove = table.addEventListener(dh.Table.EVENT_UPDATED, event => {
      const { rows: vp, columns } = (event as CustomEvent).detail as { rows: { get(c: unknown): unknown }[]; columns: { name: string }[] };
      setRows(vp.map(r => Object.fromEntries(columns.map(c => [c.name, toJs(r.get(c))]))));
    });
    return () => {
      remove();
      (subscription as unknown as { close?: () => void } | undefined)?.close?.();
    };
  }, [dh, table, maxRows]);
  return rows;
}
