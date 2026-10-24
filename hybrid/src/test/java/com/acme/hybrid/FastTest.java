package com.acme.hybrid;

import static io.deephaven.util.QueryConstants.NULL_DOUBLE;
import static io.deephaven.util.QueryConstants.NULL_LONG;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

/**
 * Unit tests for the formula functions. They are plain static methods, so they test like any
 * Java code, with no Deephaven engine. Run with `mvn test`. The Deephaven-level checks (same
 * values as the Python UDF, listener correctness, both entry points) are the Python
 * integration tests in src/test/python.
 */
class FastTest {

    @Test
    void scoreMatchesTheFormula() {
        final double px = 101.0, ma = 100.5, vwap = 100.0;
        final double expected = Math.tanh(50 * (ma - vwap) / vwap) - 0.5 * Math.tanh(20 * (px - ma) / ma);
        assertEquals(expected, Fast.score(px, ma, vwap), 1e-12);
    }

    @Test
    void scoreIsNaNForNaNOrZeroInputs() {
        assertTrue(Double.isNaN(Fast.score(Double.NaN, 100, 100)));
        assertTrue(Double.isNaN(Fast.score(100, 100, 0)));
    }

    @Test
    void deephavenNullsPropagateAsNull() {
        // A null cell arrives as the NULL_DOUBLE sentinel, not NaN; the result must be null too.
        assertEquals(NULL_DOUBLE, Fast.score(NULL_DOUBLE, 100, 100));
        assertEquals(NULL_DOUBLE, Fast.score(100, 100, NULL_DOUBLE));
        assertEquals(NULL_DOUBLE, Fast.dv01(NULL_LONG, 99.5, 7.5));
    }

    @Test
    void dv01() {
        assertEquals(7.4625, Fast.dv01(100, 99.5, 7.5), 1e-12);
    }
}
