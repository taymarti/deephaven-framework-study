# The Java entry point on a Python-console server (the pip server runs only Python app
# scripts): this loader hands control to the jar, then adds the parts that belong in Python.
# On a Groovy-console server use src/main/resources/app.d/groovy-console/ instead (same jar, a Groovy one-liner).
#
# Java primary:      com.acme.hybrid.HybridApp.start() builds the whole graph in Java and
#                    returns name -> table.
# Python subordinate: an action on the Java-built flips table (alerting, routing, I/O) and a
#                    Python-owned output table, both ordinary Python Deephaven code.
import jpy
from deephaven import dtypes as dht
from deephaven import new_table
from deephaven.column import long_col, string_col
from deephaven.stream import blink_to_append_only
from deephaven.stream.table_publisher import table_publisher
from deephaven.table import Table
from deephaven.table_listener import listen

# 1. Publish the Java tables into the scope (the shared namespace clients open by name and
#    other PQs reach as pq://<PQ>/scope/<name>). For app-only fields instead, use
#    deephaven.appmode.get_app_state()[name] = table.
_it = jpy.get_type("com.acme.hybrid.HybridApp").start().entrySet().iterator()
while _it.hasNext():
    _e = _it.next()
    globals()[_e.getKey()] = Table(j_table=_e.getValue())

# 2. A Python action subordinate to the Java graph: react to each flip the Java listener
#    published. Here it only counts and records alerts; a real one would call an order
#    gateway or a notification service, which is I/O-bound work Python does fine.
_alerts_blink, _alerts_pub = table_publisher("hy_alerts", {"Sym": dht.string, "To": dht.string,
                                                          "AlertNo": dht.int64})
hy_alerts = blink_to_append_only(_alerts_blink)
_count = [0]


def _on_flips(update, is_replay):
    added = update.added()
    syms, tos = list(added.get("Sym", [])), list(added.get("To", []))
    if not syms:
        return
    nos = list(range(_count[0] + 1, _count[0] + 1 + len(syms)))
    _count[0] += len(syms)
    _alerts_pub.add(new_table([string_col("Sym", syms), string_col("To", tos), long_col("AlertNo", nos)]))


# do_replay=True: the Java graph was already ticking while this script ran, so flips may exist
# before the listener attaches; replay delivers them as "added" first, so none are missed.
_hy_alert_handle = listen(hy_flips, _on_flips, do_replay=True, description="python alert action on Java flips")
