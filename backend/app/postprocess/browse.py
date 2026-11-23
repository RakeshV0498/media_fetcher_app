"""Folder browsing confined to an allow-list of roots (used by node agents and the controller fallback)."""
from __future__ import annotations

from pathlib import Path

from .mover import PathNotAllowed


def inside(path: Path, roots: list[Path]) -> bool:
    p = path.resolve()
    return any(p == r.resolve() or r.resolve() in p.parents for r in roots)


def _check(path: str, roots: list[Path]) -> Path:
    p = Path(path)
    if not p.is_absolute() or ".." in p.parts or not inside(p, roots):
        raise PathNotAllowed(f"{path} is outside the allowed media roots")
    return p


def browse(path: str, roots: list[Path]) -> dict:
    if not roots:
        raise PathNotAllowed("no media roots are configured")
    if not path:
        return {"path": "", "parent": None, "dirs": [str(r) for r in roots], "roots": [str(r) for r in roots],
                "absolute": True}
    p = _check(path, roots)
    if not p.is_dir():
        raise NotADirectoryError(f"{path} is not a folder")
    dirs = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.is_symlink() and not d.name.startswith("."))
    at_root = any(p.resolve() == r.resolve() for r in roots)
    return {"path": str(p), "parent": "" if at_root else str(p.parent), "dirs": dirs,
            "roots": [str(r) for r in roots], "absolute": False}


def make_dir(path: str, roots: list[Path]) -> dict:
    p = _check(path, roots)
    p.mkdir(parents=True, exist_ok=True)
    return {"path": str(p)}
