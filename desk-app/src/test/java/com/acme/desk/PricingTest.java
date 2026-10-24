package com.acme.desk;

import static io.deephaven.util.QueryConstants.NULL_DOUBLE;
import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

/** Unit tests for the pricing functions (plain Java, no engine). Run with `mvn -f java/pom.xml test`. */
class PricingTest {

    @Test
    void textbookCall() {
        // S=100, K=100, T=1, vol=20%, r=5%: call = 10.4506, put = 5.5735 (standard reference values)
        assertEquals(10.4506, Pricing.price(100, 100, 1, 0.2, 0.05, true), 1e-3);
        assertEquals(5.5735, Pricing.price(100, 100, 1, 0.2, 0.05, false), 1e-3);
    }

    @Test
    void putCallParity() {
        final double c = Pricing.price(105, 100, 0.5, 0.3, 0.03, true), p = Pricing.price(105, 100, 0.5, 0.3, 0.03, false);
        assertEquals(105 - 100 * Math.exp(-0.03 * 0.5), c - p, 1e-6);
    }

    @Test
    void deltaBounds() {
        assertEquals(0.6368, Pricing.delta(100, 100, 1, 0.2, 0.05, true), 1e-3);
        assertEquals(0.6368 - 1, Pricing.delta(100, 100, 1, 0.2, 0.05, false), 1e-3);
    }

    @Test
    void nullsPropagate() {
        assertEquals(NULL_DOUBLE, Pricing.price(NULL_DOUBLE, 100, 1, 0.2, 0.05, true));
        assertEquals(NULL_DOUBLE, Pricing.gamma(100, 100, NULL_DOUBLE, 0.2, 0.05));
    }
}
