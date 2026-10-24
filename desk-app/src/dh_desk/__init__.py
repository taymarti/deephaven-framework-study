"""
dh-desk: an options risk desk on Deephaven, built from three languages, each where it is strongest.

  Python  (this package)  owns the application: market-data feed, the table graph, actions
                          (alerting), the internal deephaven.ui ops dashboard, entry points.
  Java    (_bundle/java)  the CPU-hot nodes: Black-Scholes pricing and Greeks per row, and a
                          stateful limit-breach tracker on the update cycle.
  React   (_bundle/web)   the trader-facing web app: live risk and book grids, a limit editor
                          and an order ticket that write back into Deephaven input tables.

Entry points (installed with the wheel):
  dh-desk-server   start Deephaven with the Java jar on its classpath and build the app
  dh-desk-web      serve the React build and proxy Deephaven's JS API to the server
"""
__version__ = "0.1.0"
