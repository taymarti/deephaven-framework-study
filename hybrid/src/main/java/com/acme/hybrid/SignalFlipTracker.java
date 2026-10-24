package com.acme.hybrid;

import io.deephaven.engine.context.ExecutionContext;
import io.deephaven.engine.rowset.RowSet;
import io.deephaven.engine.table.ColumnDefinition;
import io.deephaven.engine.table.ColumnSource;
import io.deephaven.engine.table.Table;
import io.deephaven.engine.table.TableDefinition;
import io.deephaven.engine.table.TableUpdate;
import io.deephaven.engine.table.impl.InstrumentedTableUpdateListenerAdapter;
import io.deephaven.engine.util.TableTools;
import io.deephaven.stream.TablePublisher;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The Java port of rung 3's Python SignalTracker: watches a one-row-per-Sym signals table
 * (Sym, Signal), detects flips (previous Signal != current Signal), keeps a position per Sym,
 * and publishes each flip as a row of a blink table (At, Step, Sym, From, To).
 *
 * Same logic, same output table shape; it runs on the update thread as compiled Java,
 * with no GIL and no per-row Python objects.
 *
 * <pre>
 *   tracker = SignalFlipTracker.attach(signals)     // from Python via jpy, or from Java
 *   tracker.flips()                                  // the output table
 * </pre>
 */
public final class SignalFlipTracker extends InstrumentedTableUpdateListenerAdapter {
    private static final TableDefinition FLIPS = TableDefinition.of(
            ColumnDefinition.ofTime("At"), ColumnDefinition.ofLong("Step"),
            ColumnDefinition.ofString("Sym"), ColumnDefinition.ofString("From"), ColumnDefinition.ofString("To"));

    private final ColumnSource<String> sym;
    private final ColumnSource<String> signal;
    private final TablePublisher publisher;
    private final Map<String, Integer> position = new HashMap<>();
    private long flips;
    private long callbacks;

    private SignalFlipTracker(Table signals) {
        super("java SignalFlipTracker", signals, false);
        this.sym = signals.getColumnSource("Sym", String.class);
        this.signal = signals.getColumnSource("Signal", String.class);
        this.publisher = TablePublisher.of("java_flips", FLIPS, t -> { }, () -> { });
        signals.getRowSet().forAllRowKeys(k -> position.put(sym.get(k), dir(signal.get(k))));
    }

    /** Create the tracker and register it on {@code signals}; keep the returned object referenced. */
    public static SignalFlipTracker attach(Table signals) {
        final SignalFlipTracker t = new SignalFlipTracker(signals);
        signals.addUpdateListener(t);
        return t;
    }

    @Override
    public void onUpdate(TableUpdate upstream) {
        callbacks++;
        upstream.added().forAllRowKeys(k -> position.put(sym.get(k), dir(signal.get(k))));
        if (upstream.modified().isEmpty()) {
            return;
        }
        final List<String> syms = new ArrayList<>(), from = new ArrayList<>(), to = new ArrayList<>();
        try (RowSet.Iterator now = upstream.modified().iterator();
             RowSet.Iterator pre = upstream.getModifiedPreShift().iterator()) {
            while (now.hasNext()) {
                final long k = now.nextLong(), kp = pre.nextLong();
                final String cur = signal.get(k), prev = signal.getPrev(kp);
                if (cur != null && !cur.equals(prev)) {
                    flips++;
                    final String s = sym.get(k);
                    position.put(s, dir(cur));
                    syms.add(s);
                    from.add(prev);
                    to.add(cur);
                }
            }
        }
        if (!syms.isEmpty()) {
            final int n = syms.size();
            final Instant at = Instant.now();
            final long step = ExecutionContext.getContext().getUpdateGraph().clock().currentStep();
            final Instant[] ats = new Instant[n];
            final long[] steps = new long[n];
            java.util.Arrays.fill(ats, at);
            java.util.Arrays.fill(steps, step);
            publisher.add(TableTools.newTable(FLIPS,
                    TableTools.instantCol("At", ats), TableTools.longCol("Step", steps),
                    TableTools.stringCol("Sym", syms.toArray(new String[0])),
                    TableTools.stringCol("From", from.toArray(new String[0])),
                    TableTools.stringCol("To", to.toArray(new String[0]))));
        }
    }

    private static int dir(String signal) {
        return "LONG".equals(signal) ? 1 : -1;
    }

    /** The blink table of flips (wrap with blinkToAppendOnly to keep history). */
    public Table flips() {
        return publisher.table();
    }

    public long flipCount() {
        return flips;
    }

    public long callbackCount() {
        return callbacks;
    }

    public int position(String s) {
        return position.getOrDefault(s, 0);
    }
}
