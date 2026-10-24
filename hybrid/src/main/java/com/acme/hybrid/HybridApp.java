package com.acme.hybrid;

import io.deephaven.api.agg.Aggregation;
import io.deephaven.api.updateby.UpdateByOperation;
import io.deephaven.engine.table.Table;
import io.deephaven.engine.table.impl.BlinkTableTools;
import io.deephaven.engine.util.TableTools;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The Java entry point: builds rung 2's trades -> signals graph and rung 3's flip tracker
 * entirely in Java, and returns the tables to publish. An application-mode script (Groovy or
 * Python) only has to call {@code HybridApp.start()} and publish the map.
 */
public final class HybridApp {
    private HybridApp() {}

    // keeps the listener reachable for the life of the app
    private static SignalFlipTracker tracker;

    public static Map<String, Object> start() {
        final Table trades = TableTools.timeTable("PT0.1s").update(
                "Sym = (ii % 3 == 0) ? `AAPL` : (ii % 3 == 1) ? `MSFT` : `NVDA`",
                "Px = 100 + 5 * Math.sin(ii / 40.0) + randomGaussian(0.0, 0.3)",
                "Qty = 100 * randomInt(1, 10)");
        final Table vwap = trades.aggBy(
                List.of(Aggregation.AggWAvg("Qty", "VWAP = Px"), Aggregation.AggLast("Last = Px"),
                        Aggregation.AggCount("Trades")),
                "Sym");
        final Table signals = trades.updateBy(UpdateByOperation.RollingAvg(50, "MA50 = Px"), "Sym")
                .lastBy("Sym")
                .naturalJoin(vwap, "Sym", "VWAP")
                .update("Signal = MA50 > VWAP ? `LONG` : `SHORT`",
                        "Score = com.acme.hybrid.Fast.score(Px, MA50, VWAP)")
                .view("Sym", "Timestamp", "Px", "MA50", "VWAP", "Signal", "Score");
        tracker = SignalFlipTracker.attach(signals);

        final Map<String, Object> out = new LinkedHashMap<>();
        out.put("hy_trades", trades);
        out.put("hy_signals", signals);
        out.put("hy_flips", BlinkTableTools.blinkToAppendOnly(tracker.flips()));
        return out;
    }

    public static SignalFlipTracker tracker() {
        return tracker;
    }
}
