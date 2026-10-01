"""A project is one game folder: which game it is, and its .lu files."""
import os
from pathlib import Path

GAME_NAMES = {"nb1": "Naughty Bear", "pip": "Panic in Paradise"}
GAME_BADGES = {"nb1": "NB1", "pip": "PiP"}
HIDDEN_DIRS = {".seamripper"}


def container_game(path):
    """'nb1' (x36), 'pip' (LUH) or None, from the first bytes of a container."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return None
    if head == b"\x05LUH":
        return "pip"
    if head == b"\x03x36":
        return "nb1"
    return None


def lu_files(folder, limit=None):
    """Every .lu under `folder` (sorted, skipping Seam Ripper's own folder)."""
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in HIDDEN_DIRS)
        out += [Path(root) / f for f in sorted(files) if f.lower().endswith(".lu")]
        if limit and len(out) >= limit:
            break
    return out


def detect_game(folder, sample=40):
    """Game of a folder, judged by the first `sample` containers in it."""
    votes = {}
    for p in lu_files(folder, sample):
        g = container_game(p)
        if g:
            votes[g] = votes.get(g, 0) + 1
    return max(votes, key=votes.get) if votes else None


class Project:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.game = detect_game(self.folder)

    @property
    def game_name(self):
        return GAME_NAMES.get(self.game, "Unknown game")

    @property
    def badge(self):
        return GAME_BADGES.get(self.game, "?")

    @property
    def state_dir(self):
        return self.folder / ".seamripper"

    def exports_dir(self, *parts):
        return self.state_dir.joinpath("exports", *parts)

    def files(self):
        return lu_files(self.folder)

    def relative(self, path):
        try:
            return str(Path(path).relative_to(self.folder))
        except ValueError:
            return str(path)
