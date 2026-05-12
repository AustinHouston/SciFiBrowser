from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np
import pyTEMlib.file_tools as ft
from tiled.adapters.array import ArrayAdapter
from tiled.adapters.mapping import MapAdapter


PYTEMLIB_MIMETYPE = "application/x-pytemlib"


def _path_from_uri(data_uri: str) -> str:
    parsed = urlparse(data_uri)
    path = unquote(parsed.path)

    if os.name == "nt" and path.startswith("/"):
        path = path.lstrip("/")

    return str(Path(path))


def _json_safe(value: Any, *, max_sequence: int = 64) -> Any:
    """Convert pyTEMlib/sidpy metadata into values Tiled can serialize."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _json_safe(value.item())
        if value.size <= max_sequence:
            return [_json_safe(item) for item in value.tolist()]
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "preview": [_json_safe(item) for item in value.ravel()[:max_sequence].tolist()],
        }
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        sequence = list(value)
        if len(sequence) <= max_sequence:
            return [_json_safe(item) for item in sequence]
        return {
            "length": len(sequence),
            "preview": [_json_safe(item) for item in sequence[:max_sequence]],
        }
    if hasattr(value, "name") and hasattr(value, "value"):
        return str(value.name)
    return str(value)


def _dimension_metadata(dataset: Any) -> list[dict[str, Any]]:
    dimensions = []
    ndim = int(getattr(dataset, "ndim", len(getattr(dataset, "shape", ()))))

    for axis in range(ndim):
        try:
            dimension = dataset.get_dimension_by_number(axis)[0]
        except Exception:
            dimension = getattr(dataset, f"dim_{axis}", None)

        if dimension is None:
            dimensions.append({"axis": axis})
            continue

        entry = {
            "axis": axis,
            "name": getattr(dimension, "name", None),
            "quantity": getattr(dimension, "quantity", None),
            "units": getattr(dimension, "units", None),
            "dimension_type": getattr(dimension, "dimension_type", None),
            "size": getattr(dimension, "size", None),
        }

        try:
            entry["slope"] = dimension.slope
        except Exception:
            pass

        dimensions.append(_json_safe(entry))

    return dimensions


def _dataset_metadata(name: str, dataset: Any, filepath: str, metadata: Any) -> dict[str, Any]:
    base = {
        "source_path": filepath,
        "source_reader": "pyTEMlib.file_tools.open_file",
        "dataset_key": name,
        "title": getattr(dataset, "title", None),
        "name": getattr(dataset, "name", None),
        "quantity": getattr(dataset, "quantity", None),
        "units": getattr(dataset, "units", None),
        "data_type": getattr(dataset, "data_type", None),
        "shape": list(getattr(dataset, "shape", ())),
        "dtype": str(getattr(dataset, "dtype", "")),
        "dimensions": _dimension_metadata(dataset),
    }

    for attribute in ("metadata", "original_metadata"):
        value = getattr(dataset, attribute, None)
        if value:
            base[attribute] = value

    if isinstance(metadata, Mapping):
        base.update(metadata)

    return _json_safe(base)


def _safe_key(raw_key: Any, fallback: str, used: set[str]) -> str:
    key = str(raw_key or fallback).strip().strip("/")
    key = key.replace("/", "_") or fallback

    candidate = key
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{key}_{suffix}"

    used.add(candidate)
    return candidate


class PyTEMlibAdapter(MapAdapter):
    """Expose each sidpy dataset returned by pyTEMlib as a Tiled array."""

    @classmethod
    def from_uris(cls, data_uri, metadata=None, **kwargs):
        filepath = _path_from_uri(data_uri)
        datasets = ft.open_file(filepath)

        if not isinstance(datasets, dict):
            datasets = {"dataset": datasets}

        children = {}
        used_keys: set[str] = set()

        for index, (name, dataset) in enumerate(datasets.items()):
            if not hasattr(dataset, "shape") or not hasattr(dataset, "dtype"):
                continue

            key = _safe_key(
                getattr(dataset, "title", None) or name,
                f"dataset_{index}",
                used_keys,
            )
            dims = tuple(
                dimension.get("name") or f"dim_{axis}"
                for axis, dimension in enumerate(_dimension_metadata(dataset))
            )
            children[key] = ArrayAdapter.from_array(
                dataset,
                shape=tuple(dataset.shape),
                dims=dims,
                metadata=_dataset_metadata(str(name), dataset, filepath, metadata),
            )

        return cls(
            children,
            metadata=_json_safe(
                {
                    "source_path": filepath,
                    "source_reader": "pyTEMlib.file_tools.open_file",
                    "dataset_count": len(children),
                }
            ),
        )

    @classmethod
    def from_catalog(cls, data_source, metadata=None, **kwargs):
        data_uri = data_source.assets[0].data_uri
        return cls.from_uris(data_uri, metadata=metadata, **kwargs)


# Keep the tutorial's adapter name working for existing catalog registrations.
EMDAdapter = PyTEMlibAdapter
