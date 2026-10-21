"""
Rung 3 - A listener is your on_data hook (when you need imperative code).

Builds on rung 2 (run 02 first). Some logic really is imperative: "when a
signal FLIPS, act and mutate my state". That's a listener: a Python callback
the engine calls during the update cycle with exactly what changed
(added / removed / modified rows, plus the previous values of modified rows).

Outputs go to a table too (a "sink" table via table_publisher), so dashboards,
clients and other tables can consume them like any other data.

  python examples/run.py examples/02_declarative_dag.py examples/03_listener_hook.py --show ex3_flips --show ex3_state_view --every 3 --times 3
"""
from deephaven import dtypes as dht
from deephaven import new_table
from deephaven.column import datetime_col, long_col, string_col
from deephaven.stream import blink_to_append_only
from deephaven.stream.table_publisher import table_publisher
from deephaven.table_listener import TableUpdate, listen
import jpy

_clock = jpy.get_type("io.deephaven.engine.context.ExecutionContext").getContext().getUpdateGraph().clock()


class SignalTracker:
    """Plain Python state, mutated from the callback (your Algorithm's self.*)."""

    def __init__(self):
        self.position = {}      # Sym -> +1 / -1
        self.flips = 0
        self.callbacks = 0

    def on_data(self, update: TableUpdate, is_replay: bool) -> None:
        self.callbacks += 1
        rows = []
        # Initial replay (do_replay=True) delivers current rows as "added".
        for sym, sig in zip(*_cols(update.added(), "Sym", "Signal")):
            self.position[sym] = 1 if sig == "LONG" else -1
        # last_by(Sym) means every new trade MODIFIES the symbol's row; compare
        # with the previous value to detect a flip.
        if update.modified_columns and "Signal" in update.modified_columns:
            now_syms, now_sigs = _cols(update.modified(), "Sym", "Signal")
            _, prev_sigs = _cols(update.modified_prev(), "Sym", "Signal")
            for sym, prev, cur in zip(now_syms, prev_sigs, now_sigs):
                if prev != cur:
                    self.flips += 1
                    self.position[sym] = 1 if cur == "LONG" else -1
                    rows.append((sym, prev, cur))
        if rows:
            ts = _now()
            _flip_pub.add(new_table([
                datetime_col("At", [ts] * len(rows)),
                long_col("Step", [_clock.currentStep()] * len(rows)),
                string_col("Sym", [r[0] for r in rows]),
                string_col("From", [r[1] for r in rows]),
                string_col("To", [r[2] for r in rows]),
            ]))


def _cols(data: dict, *names):
    return [list(data.get(n, [])) for n in names]


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


ex3_tracker = SignalTracker()

# Sink table for the hook's outputs.
_flips_blink, _flip_pub = table_publisher(
    "ex3_flips", {"At": dht.Instant, "Step": dht.int64, "Sym": dht.string, "From": dht.string, "To": dht.string}
)
ex3_flips = blink_to_append_only(_flips_blink)

# Re-running this script in a live session would otherwise STACK listeners:
# rebinding the name does not stop the old one. Stop it explicitly.
try:
    ex3_handle.stop()
except NameError:
    pass

# Register the hook. Keep the handle referenced, or the listener is released.
ex3_handle = listen(ex2_signals, ex3_tracker.on_data, do_replay=True, description="ex3 SignalTracker")

# Surface the Python state as a table (snapshot on a timer) so we can watch it.
from deephaven import time_table

# Formulas can call typed Python functions (the return hints set column types).
def ex3_callbacks() -> int:
    return ex3_tracker.callbacks


def ex3_flip_count() -> int:
    return ex3_tracker.flips


def ex3_positions() -> str:
    return ", ".join(f"{s}:{'+1' if p > 0 else '-1'}" for s, p in sorted(ex3_tracker.position.items()))


# NOTE: formulas are recomputed only when their INPUT columns change. These
# reference no columns, so they're evaluated once per ADDED row - hence a
# fresh row each second (then tail), not last_by() (which only modifies).
ex3_state_view = time_table("PT1s").update([
    "Callbacks = ex3_callbacks()",
    "Flips = ex3_flip_count()",
    "Positions = ex3_positions()",
]).tail(5)
