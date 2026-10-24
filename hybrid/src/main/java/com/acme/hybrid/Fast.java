package com.acme.hybrid;

import static io.deephaven.util.QueryConstants.NULL_DOUBLE;
import static io.deephaven.util.QueryConstants.NULL_LONG;

/**
 * Row functions called straight from Deephaven formulas, e.g.
 * {@code update("Score = com.acme.hybrid.Fast.score(Px, MA50, VWAP)")}.
 * Static, pure and primitive-typed: the formula compiler calls them per row with no boxing
 * and no Python crossing.
 *
 * Nulls: Deephaven passes a null primitive as a sentinel (QueryConstants.NULL_DOUBLE, a very
 * large negative number), not as NaN. Check for it, and return the sentinel to mean null.
 */
public final class Fast {
    private Fast() {}

    /** A made-up but non-trivial scoring function (the kind of thing people write as a Python UDF). */
    public static double score(double px, double ma, double vwap) {
        if (px == NULL_DOUBLE || ma == NULL_DOUBLE || vwap == NULL_DOUBLE) {
            return NULL_DOUBLE;
        }
        if (Double.isNaN(px) || Double.isNaN(ma) || Double.isNaN(vwap) || vwap == 0 || ma == 0) {
            return Double.NaN;
        }
        final double trend = (ma - vwap) / vwap;
        final double stretch = (px - ma) / ma;
        return Math.tanh(50 * trend) - 0.5 * Math.tanh(20 * stretch);
    }

    /** Dollar value of a basis point: qty * px * duration / 10,000. */
    public static double dv01(long qty, double px, double duration) {
        if (qty == NULL_LONG || px == NULL_DOUBLE || duration == NULL_DOUBLE) {
            return NULL_DOUBLE;
        }
        return qty * px * duration / 10_000.0;
    }
}
