from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = Path("/Users/austin/Desktop/Projects")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_API_KEY = "secret"
DEFAULT_CATALOG = PROJECT_ROOT / "catalog.db"
DEFAULT_CONFIG = PROJECT_ROOT / "config.yml"
DEFAULT_RUNTIME_CONFIG = PROJECT_ROOT / ".scifibrowser.config.yml"
PYTEMLIB_MIMETYPE = "application/x-pytemlib"

PYTEMLIB_EXTENSIONS = (
    ".dm3",
    ".dm4",
    ".emd",
    ".h5",
    ".hdf5",
    ".hf5",
    ".ibw",
    ".ndata",
    ".tif",
    ".tiff",
)
