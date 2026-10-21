"""
Rung 4 - Many feeds, one checkpoint.

This is the closest analogue of your framework's core loop:
  * Feed A is engine-native (a time_table standing in for Kafka etc.).
  * Feeds B and C are YOUR asyncio tasks, running on an event loop in a
    background thread, pushing rows whenever they like via table_publisher.
  * merged_listen() is the "synchronizer": ONE callback per update cycle with
    whatever every feed delivered in that cycle, and a consistent view of all
    the tables at that step.

What it measures: rows per feed per checkpoint, and how long asyncio rows sat
buffered before the engine's cycle picked them up (the latency floor).

  python examples/run.py examples/04_feeds_and_checkpoints.py --show ex4_checkpoints --every 6 --times 1 --tail 12
"""
import asyncio
import random
import threading
import time

import jpy
import numpy as np
from deephaven import dtypes as dht
from deephaven import new_table, time_table
from deephaven.column import double_col, int_col, long_col, string_col
from deephaven.execution_context import get_exec_ctx
from deephaven.stream import blink_to_append_only
from deephaven.stream.table_publisher import table_publisher
from deephaven.table_listener import merged_listen

# Re-run safety: stop the previous run's feeds and listener (see rung 3).
try:
    ex4_stop.set()
    ex4_handle.stop()
except NameError:
    pass
ex4_stop = threading.Event()

_ctx = get_exec_ctx()  # background threads need the engine's execution context
_clock = jpy.get_type("io.deephaven.engine.context.ExecutionContext").getContext().getUpdateGraph().clock()

# --- Feed A: engine-native source ------------------------------------------
ex4_quotes = time_table("PT0.25s").update("Mid = 100 + randomGaussian(0.0, 0.1)")

# --- Feeds B, C: asyncio tasks -> table_publisher --------------------------
_orders_blink, _orders_pub = table_publisher(
    "ex4_orders", {"OrderId": dht.int64, "Side": dht.string, "SentMs": dht.double})
_signals_blink, _signals_pub = table_publisher(
    "ex4_signals", {"Name": dht.string, "Value": dht.double, "SentMs": dht.double})
ex4_orders = blink_to_append_only(_orders_blink)
ex4_signals = blink_to_append_only(_signals_blink)


# The stop event is passed IN, not read from the global: a global lookup would
# see the NEXT run's (unset) event and these tasks would never stop.
async def order_feed(stop: threading.Event):
    oid = 0
    while not stop.is_set():
        await asyncio.sleep(random.uniform(0.05, 0.4))   # bursty, unsynchronized
        oid += 1
        with _ctx:
            _orders_pub.add(new_table([
                long_col("OrderId", [oid]),
                string_col("Side", [random.choice(["Buy", "Sell"])]),
                double_col("SentMs", [time.time() * 1000]),
            ]))


async def signal_feed(stop: threading.Event):
    while not stop.is_set():
        await asyncio.sleep(0.7)
        with _ctx:
            _signals_pub.add(new_table([
                string_col("Name", ["momentum"]),
                double_col("Value", [random.gauss(0, 1)]),
                double_col("SentMs", [time.time() * 1000]),
            ]))


async def _main(stop: threading.Event):
    await asyncio.gather(order_feed(stop), signal_feed(stop))

threading.Thread(target=asyncio.run, args=(_main(ex4_stop),), daemon=True, name="ex4-asyncio").start()

# --- The synchronizer: one callback per cycle across all feeds -------------
_cp_blink, _cp_pub = table_publisher("ex4_checkpoints", {
    "Step": dht.int64, "Updated": dht.string,
    "QuotesAdded": dht.int32, "OrdersAdded": dht.int32, "SignalsAdded": dht.int32,
    "OrdersTotal": dht.int64, "MaxBufferedMs": dht.double,
})
ex4_checkpoints = blink_to_append_only(_cp_blink)


ex4_errors = []  # an uncaught exception would permanently stop the listener


def on_checkpoint(updates: dict, is_replay: bool) -> None:
    try:
        _on_checkpoint(updates)
    except Exception as e:  # keep the synchronizer alive; record the failure
        ex4_errors.append(repr(e))


def _on_checkpoint(updates: dict) -> None:
    now_ms = time.time() * 1000
    added = {n: 0 for n in ("quotes", "orders", "signals")}
    waits = []
    for tbl, upd in updates.items():
        if upd is None:  # every watched table is passed; None = no change this cycle
            continue
        name = next((n for t, n in _watch_named if t.j_table.equals(tbl.j_table)), "?")
        data = upd.added()
        n = len(next(iter(data.values()))) if data else 0
        added[name] = n
        if "SentMs" in data and n:
            waits.append(float(np.max(now_ms - data["SentMs"])))
    _cp_pub.add(new_table([
        long_col("Step", [_clock.currentStep()]),
        string_col("Updated", [",".join(sorted(k for k, v in added.items() if v))]),
        int_col("QuotesAdded", [added["quotes"]]),
        int_col("OrdersAdded", [added["orders"]]),
        int_col("SignalsAdded", [added["signals"]]),
        # Reading ANOTHER table inside the callback sees the same step: consistent.
        long_col("OrdersTotal", [ex4_orders.size]),
        double_col("MaxBufferedMs", [max(waits) if waits else float("nan")]),
    ]))


_watch_named = [(ex4_quotes, "quotes"), (ex4_orders, "orders"), (ex4_signals, "signals")]
ex4_handle = merged_listen([t for t, _ in _watch_named], on_checkpoint, description="ex4 synchronizer")
