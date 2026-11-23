from dataclasses import dataclass


@dataclass
class RawItem:
    title: str
    link: str | None = None
    magnet: str | None = None
    torrent_url: str | None = None
    size_text: str | None = None
    seeders: int | None = None
    leechers: int | None = None
    published: str | None = None
