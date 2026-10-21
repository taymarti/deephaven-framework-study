package com.acme;

/** A user-supplied Java library, called directly from Deephaven formulas (no Python crossing). */
public final class Risk {
    private Risk() {}

    /** Dollar value of a basis point for a position: qty * px * modified duration / 10,000. */
    public static double dv01(long qty, double px, double duration) {
        return qty * px * duration / 10_000.0;
    }
}
