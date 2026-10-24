"""
Market data. Python's strength: integrating with feeds and SDKs. A real desk would wrap a vendor
or Kafka client here; this one random-walks spot prices on a background thread and pushes them
into the graph through a table_publisher (rows land at the next update cycle).
"""
from __future__ import annotations

import random
import threading

from deephaven import dtypes as dht
from deephaven import new_table
from deephaven.column import double_col, string_col
from deephaven.stream.table_publisher import table_publisher

UNDERLYINGS = {"AAPL": 190.0, "MSFT": 410.0, "NVDA": 120.0}


class SpotFeed:
    """Spot prices as a blink table (only each cycle's new rows); aggregate it with last_by."""

    def __init__(self, hz: float = 4.0, vol_per_tick: float = 0.0015, seed: int = 7):
        self.table, self._pub = table_publisher("spot_feed", {"Underlying": dht.string, "Spot": dht.double})
        self._px = dict(UNDERLYINGS)
        self._rnd = random.Random(seed)
        self._period, self._vol = 1.0 / hz, vol_per_tick
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dh-desk-spot-feed", daemon=True)

    def start(self) -> SpotFeed:
        self._push()  # an initial price for every underlying, before anything reads them
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _push(self, names=None) -> None:
        names = list(names or self._px)
        self._pub.add(new_table([string_col("Underlying", names), double_col("Spot", [self._px[n] for n in names])]))

    def _run(self) -> None:
        while not self._stop.wait(self._period):
            name = self._rnd.choice(list(self._px))
            self._px[name] *= 1.0 + self._rnd.gauss(0.0, self._vol)
            self._push([name])
