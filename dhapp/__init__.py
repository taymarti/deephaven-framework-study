"""
dhapp: recipes and an application model on top of Deephaven (and dhfw).

  App        four roles (source, stage, action, surface), three modes (live, backtest, test)
  Catalog    logical table names resolved by where the app runs (same PQ, same plant, other plant, laptop)
  recipes    trading and risk building blocks (tables in, tables out)
  schemas    standard table shapes and boundary validation
  store      persistence: snapshots, daily partitions, intraday logs, editable state
  ui         a dashboard from an App, and the components to build your own

Engine operations stay plain Deephaven: any stage can use the full table API.
"""
from dhapp.app import App, LIVE, BACKTEST, TEST  # noqa: F401
from dhapp.catalog import Catalog  # noqa: F401
from dhapp import recipes, schemas, store  # noqa: F401
