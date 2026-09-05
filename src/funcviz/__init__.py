"""funcviz — turn Azure Functions verbose runtime logs into an execution timeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Read from distribution metadata so __version__ can never drift from the
    # version declared in pyproject.toml (issue #35).
    __version__ = version("funcviz")
except PackageNotFoundError:  # pragma: no cover - uninstalled source checkout
    __version__ = "0.0.0+unknown"
