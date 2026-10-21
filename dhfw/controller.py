"""
Importing shared code from the PQ controller's repository.

Enterprise: deephaven_enterprise.controller_import (meta_import / exec_script).
Community: the same calls read from a local checkout of that repository at
DHFW_CONTROLLER_ROOT (default: current directory), so `import controller.pkg.mod`
works unchanged.
"""
import importlib.abc
import importlib.machinery
import importlib.util
import os
import pathlib
import sys

from dhfw.runtime import is_enterprise


def _root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DHFW_CONTROLLER_ROOT", ".")).resolve()


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self, prefix: str, root: pathlib.Path):
        self.prefix, self.root = prefix, root

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.prefix and not fullname.startswith(self.prefix + "."):
            return None
        parts = fullname.split(".")[1:]
        pkg = self.root.joinpath(*parts)
        if pkg.is_dir():  # a package directory, with or without __init__.py
            init = pkg / "__init__.py"
            if init.exists():
                return importlib.util.spec_from_file_location(fullname, init, submodule_search_locations=[str(pkg)])
            spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
            spec.submodule_search_locations = [str(pkg)]
            return spec
        mod = self.root.joinpath(*parts[:-1], parts[-1] + ".py") if parts else None
        return importlib.util.spec_from_file_location(fullname, mod) if mod and mod.exists() else None


def meta_import(root: str = "controller") -> None:
    if is_enterprise():
        from deephaven_enterprise.controller_import import meta_import as mi
        return mi(root)
    if not any(isinstance(f, _Finder) and f.prefix == root for f in sys.meta_path):
        sys.meta_path.insert(0, _Finder(root, _root()))


def exec_script(path: str, globals=None) -> None:
    if is_enterprise():
        from deephaven_enterprise.controller_import import exec_script as es
        return es(path, globals)
    code = (_root() / path).read_text(encoding="utf-8")
    exec(compile(code, str(_root() / path), "exec"), globals if globals is not None else {})
