"""
Row/column ACLs on a PQ's published tables.

Enterprise: pass an edge-ACL builder function; it runs against deephaven_enterprise.edge_acl.
Community: no ACL support; the table is returned unchanged and a warning is logged once.
"""
import logging

from dhfw.runtime import is_enterprise

_log = logging.getLogger("dhfw")
_warned = False


def apply_acl(table, enterprise_acl_fn):
    """enterprise_acl_fn(table, edge_acl_module) -> table, called only on Enterprise."""
    global _warned
    if is_enterprise():
        from deephaven_enterprise import edge_acl
        return enterprise_acl_fn(table, edge_acl)
    if not _warned:
        _log.warning("dhfw: ACLs are not enforced on Community; tables are published unrestricted")
        _warned = True
    return table
