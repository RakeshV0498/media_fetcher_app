from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Node, Setting, Tag

NODES = ["pi5", "pi4"]
# (name, kind, node, category, final_path)
TAGS = [
    ("Tamil Movie", "movie", "pi5", "tamil-movies", "/media/movies/Tamil"),
    ("English Movie", "movie", "pi5", "english-movies", "/media/movies/English"),
    ("Dubbed Movie", "movie", "pi5", "dubbed-movies", "/media/movies/Dubbed"),
    ("Indian Language Movie", "movie", "pi5", "indian-movies", "/media/movies/Indian"),
    ("TV Show", "tv", "pi4", "tv", "/media/tv"),
    ("Anime", "anime", "pi4", "anime", "/media/anime"),
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
