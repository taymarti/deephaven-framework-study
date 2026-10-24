import type { ReactNode } from 'react';
import { useLiveRows, useTable } from '../hooks';
import type { Row } from '../deephaven';
import { text } from '../format';

export interface Column {
  key: string;
  label?: string;
  format?: (v: unknown) => string;
  align?: 'left' | 'right';
  render?: (row: Row) => ReactNode;
}

/** A small live grid over a published table: the viewport ticks as the server updates. */
export function LiveGrid({ table, columns, maxRows = 50, rowClass, newestFirst = false }: {
  table: string;
  columns: Column[];
  maxRows?: number;
  rowClass?: (row: Row) => string | undefined;
  newestFirst?: boolean;
}) {
  const rows = useLiveRows(useTable(table), maxRows);
  const shown = newestFirst ? [...rows].reverse() : rows;
  return (
    <table className="grid">
      <thead>
        <tr>{columns.map(c => <th key={c.key} className={c.align ?? 'right'}>{c.label ?? c.key}</th>)}</tr>
      </thead>
      <tbody>
        {shown.map((row, i) => (
          <tr key={i} className={rowClass?.(row)}>
            {columns.map(c => (
              <td key={c.key} className={c.align ?? 'right'}>{c.render ? c.render(row) : (c.format ?? text)(row[c.key])}</td>
            ))}
          </tr>
        ))}
        {shown.length === 0 && <tr><td colSpan={columns.length} className="empty">no rows yet</td></tr>}
      </tbody>
    </table>
  );
}
