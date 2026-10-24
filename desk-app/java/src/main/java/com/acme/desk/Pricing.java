package com.acme.desk;

import static io.deephaven.util.QueryConstants.NULL_DOUBLE;

/**
 * Black-Scholes price and Greeks, called per row from Deephaven formulas:
 * <pre>update("Price = com.acme.desk.Pricing.price(Spot, Strike, Tenor, Vol, Rate, IsCall)")</pre>
 *
 * Why Java: this is pure per-row arithmetic over every option in the book, recomputed on every
 * spot tick. As compiled Java it runs inside the formula's generated code with no Python crossing
 * and no GIL (a Python UDF of the same math was 4.7-6.5x slower in hybrid/'s benchmark).
 *
 * Nulls: Deephaven passes a null double as QueryConstants.NULL_DOUBLE (not NaN); propagate it.
 */
public final class Pricing {
    private Pricing() {}

    public static double price(double s, double k, double t, double vol, double r, boolean isCall) {
        if (isNull(s, k, t, vol, r)) return NULL_DOUBLE;
        if (t <= 0 || vol <= 0) return Math.max(isCall ? s - k : k - s, 0.0);
        final double d1 = d1(s, k, t, vol, r), d2 = d1 - vol * Math.sqrt(t);
        final double df = Math.exp(-r * t);
        return isCall ? s * cdf(d1) - k * df * cdf(d2) : k * df * cdf(-d2) - s * cdf(-d1);
    }

    public static double delta(double s, double k, double t, double vol, double r, boolean isCall) {
        if (isNull(s, k, t, vol, r)) return NULL_DOUBLE;
        if (t <= 0 || vol <= 0) return isCall ? (s > k ? 1.0 : 0.0) : (s < k ? -1.0 : 0.0);
        final double n = cdf(d1(s, k, t, vol, r));
        return isCall ? n : n - 1.0;
    }

    public static double gamma(double s, double k, double t, double vol, double r) {
        if (isNull(s, k, t, vol, r)) return NULL_DOUBLE;
        if (t <= 0 || vol <= 0) return 0.0;
        return pdf(d1(s, k, t, vol, r)) / (s * vol * Math.sqrt(t));
    }

    public static double vega(double s, double k, double t, double vol, double r) {
        if (isNull(s, k, t, vol, r)) return NULL_DOUBLE;
        if (t <= 0 || vol <= 0) return 0.0;
        return s * pdf(d1(s, k, t, vol, r)) * Math.sqrt(t) / 100.0; // per vol point
    }

    private static double d1(double s, double k, double t, double vol, double r) {
        return (Math.log(s / k) + (r + 0.5 * vol * vol) * t) / (vol * Math.sqrt(t));
    }

    private static double pdf(double x) {
        return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
    }

    /** Standard normal CDF (Zelen and Severo, |error| < 7.5e-8). */
    static double cdf(double x) {
        final double t = 1.0 / (1.0 + 0.2316419 * Math.abs(x));
        final double poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
        final double tail = pdf(x) * poly;
        return x >= 0 ? 1.0 - tail : tail;
    }

    private static boolean isNull(double... xs) {
        for (double x : xs) {
            if (x == NULL_DOUBLE || Double.isNaN(x)) return true;
        }
        return false;
    }
}
