import { useActionState } from 'react';
import { useLiveRows, useTable } from '../hooks';

/**
 * Writes go into Deephaven input tables through the JS API (table.inputTable().addRow).
 * The server's graph recomputes from them like from any other source: no server code per write.
 * React 19 form actions (useActionState) handle pending state and the result message.
 */

export function LimitEditor() {
  const limits = useTable('limits');
  const desks = useLiveRows(limits).map(r => String(r.Desk));
  const [message, submit, pending] = useActionState(async (_prev: string, form: FormData) => {
    const desk = String(form.get('desk'));
    const limit = Number(form.get('limit'));
    if (!(limit > 0)) return 'Enter a positive limit';
    await (await limits.inputTable()).addRow({ Desk: desk, DeltaLimit: limit });
    return `${desk} limit set to $${limit.toLocaleString()}`;
  }, '');
  return (
    <form action={submit} className="form">
      <label>Desk <select name="desk">{desks.map(d => <option key={d}>{d}</option>)}</select></label>
      <label>Delta limit ($) <input name="limit" type="number" step="100000" min="0" defaultValue={3_000_000} /></label>
      <button disabled={pending}>Set limit</button>
      <output>{message}</output>
    </form>
  );
}

export function OrderTicket() {
  const tickets = useTable('tickets');
  const [message, submit, pending] = useActionState(async (_prev: string, form: FormData) => {
    const row = {
      Desk: String(form.get('desk')),
      Trader: String(form.get('trader') || 'web'),
      Underlying: String(form.get('underlying')),
      Type: String(form.get('type')),
      Strike: Number(form.get('strike')),
      Tenor: Number(form.get('tenor')),
      Qty: Number(form.get('side')) * Number(form.get('qty')),
    };
    if (!(row.Strike > 0 && row.Tenor > 0 && row.Qty !== 0)) return 'Strike, tenor and quantity are required';
    await (await tickets.inputTable()).addRow(row);
    return `Booked ${row.Qty > 0 ? 'buy' : 'sell'} ${Math.abs(row.Qty)} ${row.Underlying} ${row.Strike}${row.Type} (${row.Desk})`;
  }, '');
  return (
    <form action={submit} className="form">
      <label>Desk <select name="desk"><option>Tech</option><option>Semis</option></select></label>
      <label>Trader <input name="trader" defaultValue="web" /></label>
      <label>Underlying <select name="underlying"><option>AAPL</option><option>MSFT</option><option>NVDA</option></select></label>
      <label>Type <select name="type"><option value="C">Call</option><option value="P">Put</option></select></label>
      <label>Strike <input name="strike" type="number" step="5" defaultValue={190} /></label>
      <label>Tenor (yrs) <input name="tenor" type="number" step="0.25" defaultValue={0.25} /></label>
      <label>Side <select name="side"><option value="1">Buy</option><option value="-1">Sell</option></select></label>
      <label>Qty <input name="qty" type="number" step="1" min="1" defaultValue={100} /></label>
      <button disabled={pending}>Book ticket</button>
      <output>{message}</output>
    </form>
  );
}
