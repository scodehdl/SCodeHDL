from importlib.metadata import version, PackageNotFoundError
try:
    __version__ = version("scode")
except PackageNotFoundError:
    __version__ = "unknown"
