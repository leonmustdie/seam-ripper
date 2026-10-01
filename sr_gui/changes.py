"""The pending edits (drafts) across all containers of a project."""
import hashlib
import json

from .luahelp import changed_functions
from .settings import home


class Draft:
    """One script being edited: what was read (`orig`) and what it is now."""

    def __init__(self, lu, index, name, form, game, orig, text=None):
        self.lu, self.index, self.name = str(lu), int(index), name
        self.form, self.game, self.orig = form, game, orig
        self.text = orig if text is None else text

    @property
    def key(self):
        return (self.lu, self.index)

    @property
    def edited(self):
        return self.text != self.orig

    def functions(self):
        return changed_functions(self.orig, self.text)

    def to_json(self):
        return {"lu": self.lu, "index": self.index, "name": self.name,
                "form": self.form, "game": self.game,
                "orig": self.orig, "text": self.text}

    @classmethod
    def from_json(cls, d):
        return cls(d["lu"], d["index"], d["name"], d.get("form", ""),
                   d.get("game"), d["orig"], d["text"])


class ChangeSet:
    """Drafts keyed by (container, record index); listeners are called with
    no arguments whenever the set of pending edits changes."""

    def __init__(self, project_folder=None):
        self.drafts = {}
        self.unchecked = set()              # keys left out of the next ship
        self.listeners = []
        self.path = None
        if project_folder is not None:
            tag = hashlib.sha1(str(project_folder).lower().encode()).hexdigest()[:12]
            self.path = home() / "drafts" / f"{tag}.json"
            self.load()

    def _fire(self):
        for fn in list(self.listeners):
            fn()

    def update(self, draft):
        """Record `draft`'s current text; drop it when it matches the original."""
        if draft.edited:
            self.drafts[draft.key] = draft
        else:
            self.drafts.pop(draft.key, None)
        self._fire()

    def discard(self, key):
        self.unchecked.discard(key)
        if self.drafts.pop(key, None) is not None:
            self._fire()

    def set_checked(self, key, on):
        """Tick or untick a pending edit for the next ship."""
        (self.unchecked.discard if on else self.unchecked.add)(key)
        self._fire()

    def clear(self):
        self.drafts.clear()
        self._fire()

    def get(self, key):
        return self.drafts.get(key)

    def pending(self):
        return sorted(self.drafts.values(), key=lambda d: (d.lu, d.index))

    def count(self):
        return len(self.drafts)

    def containers(self):
        return {d.lu for d in self.drafts.values()}

    def by_container(self, only=None):
        out = {}
        for d in self.pending():
            if only is None or d.key in only:
                out.setdefault(d.lu, []).append(d)
        return out

    def save(self):
        if not self.path:
            return
        try:
            if not self.drafts:
                if self.path.exists():
                    self.path.unlink()
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(
                [d.to_json() for d in self.pending()]), encoding="utf-8")
        except OSError:
            pass

    def load(self):
        try:
            for d in json.loads(self.path.read_text(encoding="utf-8")):
                dr = Draft.from_json(d)
                if dr.edited:
                    self.drafts[dr.key] = dr
        except (OSError, ValueError, KeyError):
            pass
