"""Probe: a second app publishes a field with the SAME name as the first app's."""
from deephaven import empty_table
from deephaven.appmode import get_app_state

app = get_app_state()
app["probe_field"] = empty_table(1).update("Src = `second app's probe_field`")
app["second_only"] = empty_table(1).update("Src = `second only`")
