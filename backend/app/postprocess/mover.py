from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..parsing.parser import parse_title
from .naming import episode_dest, movie_dest

VIDEO_EXT = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts", ".wmv"}
SUB_EXT = {".srt", ".ass", ".ssa", ".sub", ".vtt"}
EXTRA_DIRS = {"sample", "samples", "extras", "featurettes", "behind the scenes", "trailers"}
MIN_MAIN_BYTES = 50 * 1024 * 1024


class NeedsAttention(Exception):
    """Cannot file safely without user input (e.g. unknown season). Never guess."""


class PathNotAllowed(Exception):
    pass


@dataclass
class MoveResult:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    duplicates: list[Path] = field(default_factory=list)  # existing destination, source kept
    skipped: list[Path] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.moved) and not self.duplicates


def _check_root(root: Path, allowed_roots: list[Path] | None) -> None:
    if allowed_roots is None:
        return
    r = root.resolve()
    if not any(r == a.resolve() or a.resolve() in r.parents for a in allowed_roots):
        raise PathNotAllowed(f"{root} is outside the allowed media roots")


def _videos(content: Path) -> tuple[list[Path], list[Path]]:
    files = [content] if content.is_file() else sorted(p for p in content.rglob("*") if p.is_file())
    vids, skipped = [], []
    for f in files:
        if f.suffix.lower() not in VIDEO_EXT:
            continue
        rel_parts = {x.lower() for x in f.relative_to(content.parent if content.is_file() else content).parts[:-1]}
        if "sample" in f.stem.lower() or rel_parts & EXTRA_DIRS:
            skipped.append(f)
        else:
            vids.append(f)
    if len(vids) > 1:  # drop tiny leftovers only when real files exist
        big = [v for v in vids if v.stat().st_size >= MIN_MAIN_BYTES]
        if big:
            skipped += [v for v in vids if v not in big]
            vids = big
    return vids, skipped


def _transfer(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)  # atomic on same filesystem
        return
    except OSError:
        pass
    tmp = dst.with_name(dst.name + ".part")
    shutil.copy2(src, tmp)
    if tmp.stat().st_size != src.stat().st_size:
        tmp.unlink(missing_ok=True)
        raise OSError(f"size mismatch copying {src} -> {dst}")
    os.replace(tmp, dst)
    src.unlink()  # only after verified copy


def _move_with_subs(src: Path, dst: Path, res: MoveResult) -> None:
    if dst.exists():
        res.duplicates.append(src)
        return
    _transfer(src, dst)
    res.moved.append((src, dst))
    for sub in src.parent.glob(f"{src.stem}*"):
        if sub.suffix.lower() in SUB_EXT and sub.is_file():
            lang = sub.stem[len(src.stem):]
            sub_dst = dst.with_name(dst.stem + lang + sub.suffix.lower())
            if not sub_dst.exists():
                _transfer(sub, sub_dst)


def file_release(content: Path, root: Path, kind: str, title: str, year: int | None = None,
                 season: int | None = None, episode: int | None = None,
                 allowed_roots: list[Path] | None = None) -> MoveResult:
    """Rename/move finished download(s) into the Jellyfin layout under `root`."""
    _check_root(root, allowed_roots)
    if not content.exists():
        raise FileNotFoundError(f"download not found at {content}")
    vids, skipped = _videos(content)
    if not vids:
        raise NeedsAttention("no video files found in download")
    res = MoveResult(skipped=skipped)
    if kind == "movie":
        main = max(vids, key=lambda p: p.stat().st_size)
        res.skipped += [v for v in vids if v is not main]
        _move_with_subs(main, movie_dest(root, title, year, main.suffix.lower()), res)
        return res
    plan: list[tuple[Path, Path]] = []
    for v in vids:
        p = parse_title(v.name)
        s = p.season if p.season is not None else season
        e = p.episode if p.episode is not None else (episode if len(vids) == 1 else None)
        if s is None or e is None:
            raise NeedsAttention(
                f"cannot determine season/episode for '{v.name}' - set the season for this show and retry")
        plan.append((v, episode_dest(root, title, s, e, v.suffix.lower())))
    if len({d for _, d in plan}) != len(plan):
        raise NeedsAttention("multiple files map to the same episode")
    for src, dst in plan:  # plan fully resolved before touching disk
        _move_with_subs(src, dst, res)
    return res


def cleanup_empty(content: Path, stop_at: Path | None = None) -> None:
    """Remove the leftover download folder if only junk (non-media) remains empty dirs."""
    if content.is_dir():
        for d in sorted((p for p in content.rglob("*") if p.is_dir()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            content.rmdir()
        except OSError:
            pass
