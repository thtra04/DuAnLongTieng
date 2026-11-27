"""Isolate learned terminology, cache and translation memory across editing workspaces."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

current = ContextVar("vsub_workspace", default="")


@contextmanager
def using(scope):
    token = current.set(scope)
    try:
        yield
    finally:
        current.reset(token)


def file_for(path: Path) -> Path:
    scope = current.get()
    return path.parent / "workspaces" / scope / path.name if scope else path
