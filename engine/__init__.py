"""Thimbleby engine: the generic core."""

from importlib.metadata import PackageNotFoundError

from engine.legacy_names import distribution_version

try:
    #: The installed package's version: the one place it is written is the package's own metadata.
    __version__ = distribution_version("thimbleby")
except PackageNotFoundError:  # run from a folder that was never installed
    __version__ = "0+unknown"
