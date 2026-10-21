import { useCallback, useEffect, useMemo, useState } from 'react';
import type { dh as DhType } from '@deephaven/jsapi-types';
import { useApi } from '@deephaven/jsapi-bootstrap';
import { useConnection } from '@deephaven/app-utils';
import {
  Button,
  Flex,
  Heading,
  Item,
  NumberField,
  Picker,
  Slider,
  Text,
  View,
} from '@deephaven/components';
import { LiveGrid } from './LiveGrid';
import { money, useIdeSession, useNamedTable, useViewportRows } from './hooks';

// --- KPIs: raw JS API viewport subscription, rendered with our own JSX -------
function Kpi({ label, value, tone }: { label: string; value: string; tone?: 'pos' | 'neg' }) {
  return (
    <View padding="size-200" borderWidth="thin" borderColor="gray-300" borderRadius="medium" flexGrow={1}>
      <Text>{label}</Text>
      <Heading level={3} margin={0} UNSAFE_className={tone}>
        {value}
      </Heading>
    </View>
  );
}

function BookKpis() {
  const { table } = useNamedTable('book_summary');
  const [s] = useViewportRows(table, 1);
  if (s == null) return <Text>Waiting for first trades…</Text>;
  const pnl = s.PnL as number;
  return (
    <Flex gap="size-200" width="100%">
      <Kpi label="Book P&L" value={money(pnl)} tone={pnl >= 0 ? 'pos' : 'neg'} />
      <Kpi label="Gross exposure" value={money(s.GrossExposure)} />
      <Kpi label="Trades" value={Number(s.Trades).toLocaleString()} />
      <Kpi label="Positions" value={String(s.Positions)} />
    </Flex>
  );
}

// --- Limit editor: write straight into a server-side INPUT table ------------
function LimitEditor({ desks, desk, onDesk }: { desks: string[]; desk: string; onDesk: (d: string) => void }) {
  const { table } = useNamedTable('risk_limits');
  const [limit, setLimit] = useState(5_000_000);
  const [status, setStatus] = useState<string>();

  const apply = async () => {
    if (table == null) return;
    try {
      // No server code involved: the JS API upserts by key column (Desk).
      const inputTable = await table.inputTable();
      await inputTable.addRow({ Desk: desk, Limit: limit });
      setStatus(`Set ${desk} limit to ${money(limit)}`);
    } catch (e) {
      setStatus(`Failed: ${e}`);
    }
  };

  return (
    <Flex direction="column" gap="size-150" margin="size-200">
      <Picker label="Desk" selectedKey={desk} onChange={k => onDesk(String(k))}>
        {desks.map(d => (
          <Item key={d}>{d}</Item>
        ))}
      </Picker>
      <NumberField
        label="Gross limit ($)"
        value={limit}
        onChange={setLimit}
        minValue={0}
        step={250_000}
        formatOptions={{ style: 'currency', currency: 'USD', maximumFractionDigits: 0 }}
      />
      <Button kind="primary" onClick={apply} disabled={table == null}>
        Apply limit
      </Button>
      {status && <Text>{status}</Text>}
    </Flex>
  );
}

// --- Stress test: invoke a Python function on the server via runCode -------
// Each tab writes to its own variable so concurrent users don't clobber each
// other (deephaven.ui gets this isolation for free via per-session state).
const STRESS_VAR = `stress_${Math.random().toString(36).slice(2, 8)}`;

function StressPanel({ desk }: { desk: string }) {
  const session = useIdeSession();
  const [shock, setShock] = useState(-5);
  const [committedShock, setCommittedShock] = useState(-5);
  const [result, setResult] = useState<{ fetch: () => Promise<DhType.Table>; version: number }>();
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (session == null) return;
    let cancelled = false;
    (async () => {
      // desk comes from the server's own Desk list; run_stress re-validates it.
      const code = `${STRESS_VAR} = run_stress(${Number(committedShock)}, ${JSON.stringify(desk)})`;
      const res = await session.runCode(code);
      if (cancelled) return;
      if (res.error) {
        setError(res.error);
        return;
      }
      setError(undefined);
      setResult(r => ({ fetch: () => session.getTable(STRESS_VAR), version: (r?.version ?? 0) + 1 }));
    })();
    return () => {
      cancelled = true;
    };
  }, [session, committedShock, desk]);

  // A second, lightweight handle on the result to compute the KPI client-side.
  const [impactTable, setImpactTable] = useState<DhType.Table>();
  useEffect(() => {
    let t: DhType.Table | undefined;
    result?.fetch().then(x => setImpactTable((t = x)));
    return () => t?.close();
  }, [result]);
  const rows = useViewportRows(impactTable, 100);
  const impact = rows.reduce((acc, r) => acc + ((r.PnLImpact as number) ?? 0), 0);

  return (
    <Flex direction="column" gap="size-150" height="100%">
      <Flex gap="size-300" alignItems="end">
        <Slider
          label={`Price shock (%) — desk: ${desk}`}
          minValue={-20}
          maxValue={20}
          step={1}
          value={shock}
          onChange={setShock}
          onChangeEnd={setCommittedShock} // only round-trip when the drag ends
          width="size-4600"
        />
        <Kpi label="Stress P&L impact" value={rows.length ? money(impact) : '–'} tone={impact >= 0 ? 'pos' : 'neg'} />
      </Flex>
      {error && <Text UNSAFE_className="neg">{error}</Text>}
      <View flexGrow={1} position="relative" minHeight="size-3000">
        {result && <LiveGrid key={result.version} fetchTable={result.fetch} />}
      </View>
    </Flex>
  );
}

// --- App shell --------------------------------------------------------------
export default function App() {
  const dh = useApi();
  const connection = useConnection();
  const { table: limitsTable } = useNamedTable('risk_limits');
  const desks = useViewportRows(limitsTable, 20).map(r => String(r.Desk));
  const [desk, setDesk] = useState('Tech');

  // Stable fetchers so LiveGrid doesn't rebuild its model on every render.
  const fetchByName = useCallback(
    (name: string) => () => connection.getObject({ type: dh.VariableType.TABLE, name }),
    [connection, dh]
  );
  const fetchDeskRisk = useMemo(() => fetchByName('desk_risk'), [fetchByName]);
  const fetchTrades = useMemo(() => fetchByName('recent_trades'), [fetchByName]);

  return (
    <div className="app">
      <header>
        <h1>Book Monitor</h1>
        <span>
          Approach (2): React + <code>@deephaven/*</code> served from :4010 &nbsp;·&nbsp;
          <a href="http://localhost:10000/iframe/widget/?name=book_dashboard" target="_blank" rel="noreferrer">
            compare with deephaven.ui ↗
          </a>
        </span>
      </header>
      <section className="kpis">
        <BookKpis />
      </section>
      <section className="card risk">
        <h2>Desk risk</h2>
        <div className="grid-host">
          <LiveGrid fetchTable={fetchDeskRisk} />
        </div>
      </section>
      <section className="card limits">
        <h2>Risk limits</h2>
        <LimitEditor desks={desks} desk={desk} onDesk={setDesk} />
      </section>
      <section className="card stress">
        <h2>Stress test</h2>
        <StressPanel desk={desk} />
      </section>
      <section className="card trades">
        <h2>Recent trades</h2>
        <div className="grid-host">
          <LiveGrid fetchTable={fetchTrades} />
        </div>
      </section>
    </div>
  );
}
