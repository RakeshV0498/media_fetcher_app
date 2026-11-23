from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    agent_url: Mapped[str] = mapped_column(String, default="")
    qbit_url: Mapped[str] = mapped_column(String, default="")
    download_dir: Mapped[str] = mapped_column(String, default="")  # where qBittorrent saves; blank = agent default
    max_concurrent: Mapped[int] = mapped_column(Integer, default=2)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)  # movie | tv | anime
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    qbit_category: Mapped[str] = mapped_column(String, default="")
    final_path: Mapped[str] = mapped_column(String, default="")
    node: Mapped[Node | None] = relationship()


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    feed_url: Mapped[str | None] = mapped_column(String, nullable=True)
    mode: Mapped[str] = mapped_column(String, default="auto")  # auto | feed | html
    selectors: Mapped[dict] = mapped_column(JSON, default=dict)
    user_agent: Mapped[str] = mapped_column(String, default="")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    cron: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    default_tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id"), nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String, default="")


class Release(Base):
    __tablename__ = "releases"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_key: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    absolute_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String, default="movie")
    suggested_tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, default="new")
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail_url: Mapped[str | None] = mapped_column(String, nullable=True)  # page listing this entry's versions
    detail_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    details_loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String, nullable=True)
    overview: Mapped[str | None] = mapped_column(String, nullable=True)
    genres: Mapped[list] = mapped_column(JSON, default=list)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    variants: Mapped[list[Variant]] = relationship(back_populates="release", cascade="all, delete-orphan")


class Variant(Base):
    __tablename__ = "variants"
    __table_args__ = (UniqueConstraint("release_id", "source_id", "ident"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    ident: Mapped[str] = mapped_column(String)  # info-hash, else link
    title: Mapped[str] = mapped_column(String, default="")
    quality: Mapped[str | None] = mapped_column(String, nullable=True)
    codec: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seeders: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leechers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    magnet: Mapped[str | None] = mapped_column(String, nullable=True)
    torrent_url: Mapped[str | None] = mapped_column(String, nullable=True)
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    release: Mapped[Release] = relationship(back_populates="variants")


class Download(Base):
    __tablename__ = "downloads"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"))
    node_name: Mapped[str] = mapped_column(String, default="")
    client_id: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="queued")
    error: Mapped[str] = mapped_column(String, default="")
    content_path: Mapped[str] = mapped_column(String, default="")
    final_files: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    release: Mapped[Release] = relationship()
    variant: Mapped[Variant] = relationship()
    tag: Mapped[Tag] = relationship()


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, default="")


class ShowMeta(Base):
    """Cache of TMDB/AniList lookups keyed by kind + normalized title (+ year)."""
    __tablename__ = "show_meta"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    """Admin-editable configuration. Secret values are stored Fernet-encrypted (see settings_store)."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, default="")
    is_secret: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
