"""Plugin-based metric registry.

Metrics self-register via the ``@metric`` decorator.  The scorer discovers
them through ``get_all_metrics()`` — it never imports individual metric
modules directly.  Adding a new metric is: create a file in this package,
subclass ``MetricPlugin``, and decorate with ``@metric("name")``.  Zero
edits to the runner or scorer.

All ``.py`` files in this package (except ``__init__``) are auto-imported
at package init time so that their ``@metric`` decorators execute.
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from typing import Any

from eval.models import MetricResult, TestCase

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class MetricPlugin(ABC):
    """Base class every metric must subclass."""

    @abstractmethod
    def score(self, trace: dict[str, Any], test_case: TestCase) -> MetricResult:
        """Evaluate *trace* against *test_case* and return a result."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_METRIC_REGISTRY: dict[str, MetricPlugin] = {}


def metric(name: str):
    """Class decorator that registers a ``MetricPlugin`` subclass."""

    def decorator(cls: type[MetricPlugin]):
        _METRIC_REGISTRY[name] = cls()
        return cls

    return decorator


def get_all_metrics() -> dict[str, MetricPlugin]:
    """Return a snapshot of every registered metric."""
    return dict(_METRIC_REGISTRY)


# ---------------------------------------------------------------------------
# Auto-discover all sibling modules so their @metric decorators fire.
# ---------------------------------------------------------------------------

def _auto_import():
    package_path = __path__  # type: ignore[name-defined]
    for _importer, mod_name, _is_pkg in pkgutil.iter_modules(package_path):
        importlib.import_module(f"{__name__}.{mod_name}")


_auto_import()
