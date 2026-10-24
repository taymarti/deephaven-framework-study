package com.acme.desk;

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
import java.util.List;

/**
 * Watches the per-desk risk table (Desk, Utilization, Breach) and emits an event row each time a
 * desk crosses into or out of breach: (At, Desk, Event = BREACH | CLEAR, Utilization).
 *
 * Why Java: it runs on every risk update, inside the update cycle, comparing previous and current
 * values row by row; as Java it costs no GIL time (the same pattern was 13-20x cheaper than Python
 * in hybrid/'s benchmark). Python then acts on the EVENTS (alerting), which are few.
 */
public final class LimitBreachTracker extends InstrumentedTableUpdateListenerAdapter {
    private static final TableDefinition EVENTS = TableDefinition.of(
            ColumnDefinition.ofTime("At"), ColumnDefinition.ofString("Desk"),
            ColumnDefinition.ofString("Event"), ColumnDefinition.ofDouble("Utilization"));

    private final ColumnSource<String> desk;
    private final ColumnSource<Boolean> breach;
    private final ColumnSource<Double> util;
    private final TablePublisher publisher;

    private LimitBreachTracker(Table risk) {
        super("java LimitBreachTracker", risk, false);
        this.desk = risk.getColumnSource("Desk", String.class);
        this.breach = risk.getColumnSource("Breach", Boolean.class);
        this.util = risk.getColumnSource("Utilization", double.class);
        this.publisher = TablePublisher.of("breach_events", EVENTS, t -> { }, () -> { });
    }

    /** Create, report desks already in breach, and register; keep the returned object referenced. */
    public static LimitBreachTracker attach(Table risk) {
        final LimitBreachTracker t = new LimitBreachTracker(risk);
        final Events initial = new Events();
        risk.getRowSet().forAllRowKeys(k -> {
            if (Boolean.TRUE.equals(t.breach.get(k))) initial.add(t.desk.get(k), "BREACH", t.util.getDouble(k));
        });
        initial.publish(t.publisher);
        risk.addUpdateListener(t);
        return t;
    }

    @Override
    public void onUpdate(TableUpdate up) {
        final Events ev = new Events();
        up.added().forAllRowKeys(k -> {
            if (Boolean.TRUE.equals(breach.get(k))) ev.add(desk.get(k), "BREACH", util.getDouble(k));
        });
        try (RowSet.Iterator now = up.modified().iterator(); RowSet.Iterator pre = up.getModifiedPreShift().iterator()) {
            while (now.hasNext()) {
                final long k = now.nextLong(), kp = pre.nextLong();
                final boolean cur = Boolean.TRUE.equals(breach.get(k)), prev = Boolean.TRUE.equals(breach.getPrev(kp));
                if (cur != prev) ev.add(desk.get(k), cur ? "BREACH" : "CLEAR", util.getDouble(k));
            }
        }
        ev.publish(publisher);
    }

    /** A blink table of breach events. */
    public Table events() {
        return publisher.table();
    }

    private static final class Events {
        final List<String> desks = new ArrayList<>(), kinds = new ArrayList<>();
        final List<Double> utils = new ArrayList<>();

        void add(String d, String kind, double u) {
            desks.add(d);
            kinds.add(kind);
            utils.add(u);
        }

        void publish(TablePublisher p) {
            if (desks.isEmpty()) return;
            final int n = desks.size();
            final Instant[] at = new Instant[n];
            final double[] u = new double[n];
            final Instant now = Instant.now();
            for (int i = 0; i < n; i++) {
                at[i] = now;
                u[i] = utils.get(i);
            }
            p.add(TableTools.newTable(EVENTS, TableTools.instantCol("At", at),
                    TableTools.stringCol("Desk", desks.toArray(new String[0])),
                    TableTools.stringCol("Event", kinds.toArray(new String[0])), TableTools.doubleCol("Utilization", u)));
        }
    }
}
