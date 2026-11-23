"""Upgrade a *populated* database (rows referencing each other), the way a real install does.
An earlier version of migration 0009 only passed on empty databases and crash-looped the app on a real one."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent


def alembic(db: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}"}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture()
def old_db(tmp_path):
    db = tmp_path / "old.db"
    assert alembic(db, "upgrade", "0008").returncode == 0
    c = sqlite3.connect(db)
    c.execute("insert into sources(name,url,mode,selectors,user_agent,interval_minutes,enabled,last_status) "
              "values('s','u','auto','{}','',60,1,'')")
    c.execute("insert into releases(release_key,title,kind,status,genres,created_at) "
              "values('k','Sintel','movie','new','[]','2026-01-01')")
    c.execute("insert into variants(release_id,source_id,ident,title,seen_at) values(1,1,'i','t','2026-01-01')")
    c.execute("insert into nodes(name,agent_url,qbit_url,download_dir,max_concurrent) values('pi5','','','',2)")
    c.execute("insert into tags(name,kind,node_id,qbit_category,final_path) values('English Movie','movie',1,'x','/media/movies/English')")
    c.execute("insert into downloads(release_id,variant_id,tag_id,node_name,client_id,status,error,content_path,final_files,created_at) "
              "values(1,1,1,'pi5','c','done','','','[]','2026-01-01')")
    c.commit()
    c.close()
    return db


def check(db: Path):
    c = sqlite3.connect(db)
    assert c.execute("select * from alembic_version").fetchall() == [("0009",)]
    assert c.execute("select title, detail_url from releases").fetchall() == [("Sintel", None)]
    assert c.execute("select count(*) from variants").fetchone() == (1,)
    assert c.execute("select count(*) from downloads").fetchone() == (1,)
    assert c.execute("pragma foreign_key_check").fetchall() == []
    assert c.execute("select name from sqlite_master where name like '%alembic_tmp%'").fetchall() == []
    assert c.execute("select final_path from tags").fetchone() == ("/media/movies/English",)  # untouched
    c.close()


def test_upgrade_with_linked_rows_succeeds(old_db):
    r = alembic(old_db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    check(old_db)


def test_upgrade_recovers_from_a_leftover_tmp_table(old_db):
    """The state the crash-looping Pi was in: a half-finished earlier rebuild left a tmp table behind."""
    c = sqlite3.connect(old_db)
    c.execute("create table _alembic_tmp_releases (id integer)")
    c.commit()
    c.close()
    r = alembic(old_db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    check(old_db)


def test_upgrade_is_repeatable_and_downgrade_works(old_db):
    assert alembic(old_db, "upgrade", "head").returncode == 0
    assert alembic(old_db, "upgrade", "head").returncode == 0                   # no-op the second time
    assert alembic(old_db, "downgrade", "0008").returncode == 0
    assert alembic(old_db, "upgrade", "head").returncode == 0
    check(old_db)
