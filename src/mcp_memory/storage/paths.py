"""项目数据目录路径工具（spec §10.3）。"""
from __future__ import annotations

from pathlib import Path


def local_cache_path(data_dir: Path, scope: str) -> Path:
    return data_dir / f"local_cache_{scope}.sqlite"


def lance_path(data_dir: Path, scope: str) -> Path:
    return data_dir / f"vectors_{scope}.lance"


def ensure_data_dir(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
