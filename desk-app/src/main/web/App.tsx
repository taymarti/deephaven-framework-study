import { Suspense, type ReactNode } from 'react';
import { LiveGrid } from './components/LiveGrid';
import { LimitEditor, OrderTicket } from './components/Forms';
import { fixed, money, percent } from './format';

function Panel({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <section className={wide ? 'panel wide' : 'panel'}>
      <h2>{title}</h2>
      <Suspense fallback={<p className="empty">connecting…</p>}>{children}</Suspense>
    </section>
  );
}

const utilBar = (row: Record<string, unknown>) => {
  const u = typeof row.Utilization === 'number' ? row.Utilization : 0;
  return (
    <span className="bar">
      <span className={u > 1 ? 'fill over' : 'fill'} style={{ width: `${Math.min(u, 1.5) / 1.5 * 100}%` }} />
      <span className="barlabel">{percent(u)}</span>
    </span>
  );
};

/**
 * The trader-facing app. React's strengths: our own layout, branding and UX, forms that write
 * back to the server, and deployment as static files. All numbers come live from Deephaven.
 */
export function App() {
  return (
    <main>
      <header>
        <h1>Options desk</h1>
        <p>Live from Deephaven: Python graph, Java pricing, React UI</p>
      </header>
      <div className="layout">
        <Panel title="Risk by desk" wide>
          <LiveGrid table="risk" rowClass={r => (r.Breach ? 'breach' : undefined)} columns={[
            { key: 'Desk', align: 'left' }, { key: 'Positions' },
            { key: 'Mv', label: 'Market value', format: money }, { key: 'DeltaDollars', label: 'Delta $', format: money },
            { key: 'GammaDollars', label: 'Gamma $ (1%)', format: money }, { key: 'VegaDollars', label: 'Vega $', format: money },
            { key: 'DeltaLimit', label: 'Delta limit', format: money },
            { key: 'Utilization', label: 'Utilization', render: utilBar },
          ]} />
        </Panel>
        <Panel title="Set a desk limit"><LimitEditor /></Panel>
        <Panel title="Book (priced in Java)" wide>
          <LiveGrid table="book" columns={[
            { key: 'Desk', align: 'left' }, { key: 'Underlying', align: 'left' }, { key: 'Type', align: 'left' },
            { key: 'Strike', format: fixed(0) }, { key: 'Tenor', format: fixed(2) }, { key: 'Qty' },
            { key: 'Spot', format: fixed(2) }, { key: 'Price', format: fixed(2) }, { key: 'Delta', format: fixed(3) },
            { key: 'Mv', label: 'Market value', format: money }, { key: 'DeltaDollars', label: 'Delta $', format: money },
          ]} />
        </Panel>
        <Panel title="Order ticket"><OrderTicket /></Panel>
        <Panel title="Breach events (Java tracker)">
          <LiveGrid table="breach_events" newestFirst rowClass={r => (r.Event === 'BREACH' ? 'breach' : undefined)} columns={[
            { key: 'At', align: 'left' }, { key: 'Desk', align: 'left' }, { key: 'Event', align: 'left' },
            { key: 'Utilization', format: percent },
          ]} />
        </Panel>
        <Panel title="Alerts (Python action)">
          <LiveGrid table="alerts" newestFirst columns={[{ key: 'Desk', align: 'left' }, { key: 'Message', align: 'left' }]} />
        </Panel>
      </div>
    </main>
  );
}
