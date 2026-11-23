from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Node, Setting, Source, Tag

NODES = ["pi5", "pi4"]
# (name, kind, node, category, final_path)
TAGS = [
    ("Tamil Movie", "movie", "pi5", "tamil-movies", "/Media_Server/05/Tamil Movies"),
    ("English Movie", "movie", "pi5", "english-movies", "/Media_Server/05/English Movies"),
    ("Dubbed Movie", "movie", "pi5", "dubbed-movies", "/Media_Server/05/Dubbed Movies"),
    ("Indian Language Movie", "movie", "pi5", "indian-movies", "/Media_Server/05/Indian Language Movies"),
    ("TV Show", "tv", "pi4", "tv", "/cloud/01"),
    ("Anime", "anime", "pi4", "anime", "/cloud/02/Anime"),
]


def seed(db: Session) -> None:
    nodes = {n.name: n for n in db.scalars(select(Node))}
    for name in NODES:
        if name not in nodes:
            nodes[name] = Node(name=name)
            db.add(nodes[name])
    env = {"pi5": (settings.node_pi5_url, settings.node_pi5_qbit_url),
           "pi4": (settings.node_pi4_url, settings.node_pi4_qbit_url)}
    for name, (agent, qbit) in env.items():
        if agent and not nodes[name].agent_url:
            nodes[name].agent_url = agent
        if qbit and not nodes[name].qbit_url:
            nodes[name].qbit_url = qbit
    db.flush()
    have = {t.name for t in db.scalars(select(Tag))}
    for name, kind, node, cat, path in TAGS:
        if name not in have:
            db.add(Tag(name=name, kind=kind, node_id=nodes[node].id,
                       qbit_category=cat, final_path=path))
    if db.get(Setting, "preferred_quality") is None:
        db.add(Setting(key="preferred_quality", value="1080p"))
    db.commit()


# Sources that publish openly licensed (public domain / Creative Commons) torrents, for trying the full flow.
EXAMPLE_SOURCES = [
    {
        "name": "WebTorrent free torrents (CC / public domain test files)",
        "url": "https://webtorrent.io/free-torrents",
        "mode": "html",
        "interval_minutes": 1440,
        "selectors": {
            "item": "li:not(:has(a[href*='wired-cd']))",  # skip the audio-only entry
            "title": "p",
            "title_regex": r"^(.*?)\s*\(torrent file\)",
            "torrent": "a[href$='.torrent']@href",
            "magnet": "a[href^='magnet:']@href",
        },
    },
]


def seed_example_sources(db: Session) -> list[Source]:
    """Add the example sources once (re-deleting one is respected). Returns newly added sources."""
    if db.get(Setting, "example_sources_seeded") is not None:
        return []
    added = []
    existing = {s.url for s in db.scalars(select(Source))}
    for spec in EXAMPLE_SOURCES:
        if spec["url"] not in existing:
            src = Source(**spec)
            db.add(src)
            added.append(src)
    db.add(Setting(key="example_sources_seeded", value="1"))
    db.commit()
    return added
