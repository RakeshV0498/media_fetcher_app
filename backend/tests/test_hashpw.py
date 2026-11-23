import runpy

from dotenv import dotenv_values

from app.auth import verify_password


def test_hashpw_line_roundtrips_through_dotenv(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("getpass.getpass", lambda _="": "s3cret pw")
    runpy.run_module("app.hashpw", run_name="__main__")
    line = capsys.readouterr().out.strip()
    assert line.startswith("AUTH_PASSWORD_HASH='$argon2")
    env = tmp_path / ".env"
    env.write_text(line + "\n")
    value = dotenv_values(env)["AUTH_PASSWORD_HASH"]
    assert verify_password("s3cret pw", value) and not verify_password("wrong", value)
