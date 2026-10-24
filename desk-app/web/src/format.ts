const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat('en-US', { style: 'percent', maximumFractionDigits: 1 });

export const money = (v: unknown) => (typeof v === 'number' ? usd.format(v) : '–');
export const percent = (v: unknown) => (typeof v === 'number' ? pct.format(v) : '–');
export const fixed = (digits: number) => (v: unknown) => (typeof v === 'number' ? v.toFixed(digits) : '–');
export const text = (v: unknown) => (v instanceof Date ? v.toLocaleTimeString() : v == null ? '–' : String(v));
