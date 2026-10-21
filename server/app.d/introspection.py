"""
Runs FIRST (see book.app). Opening the update-performance ancestors log before
any other tables exist means every node's dependencies get recorded, so
deephaven.perfmon.ancestor_dot/svg/image can draw the full graph later.
Entries created before this log is opened are recorded without ancestry.
"""
from deephaven import perfmon

global perf_upl, perf_ancestors, perf_server_state
perf_upl = perfmon.update_performance_log()
perf_ancestors = perfmon.update_performance_ancestors_log()
perf_server_state = perfmon.server_state_log()
