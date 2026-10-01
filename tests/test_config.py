"""Tests for the YAML-subset config parser and validation."""

import pytest

from uptimebeacon.config import (
    AppConfig,
    ConfigError,
    Target,
    dump_config,
    load_config,
    parse_simple_yaml,
    save_config,
)


def test_parse_scalars():
    data = parse_simple_yaml(
        "a: 1\nb: 2.5\nc: true\nd: no\ne: hello\nf: null\ng: 'quoted # not comment'\n"
    )
    assert data == {
        "a": 1, "b": 2.5, "c": True, "d": False,
        "e": "hello", "f": None, "g": "quoted # not comment",
    }


def test_parse_comments_and_blank_lines():
    data = parse_simple_yaml("# top comment\n\na: 1  # trailing\n")
    assert data == {"a": 1}


def test_parse_nested_mapping_and_list_of_mappings():
    text = (
        "database: uptime.db\n"
        "targets:\n"
        "  - name: api\n"
        "    url: https://example.com/health\n"
        "    interval: 60\n"
        "    expected_status: [200, 204]\n"
        "  - name: web\n"
        "    url: https://example.com\n"
    )
    data = parse_simple_yaml(text)
    assert data["database"] == "uptime.db"
    assert data["targets"][0]["name"] == "api"
    assert data["targets"][0]["expected_status"] == [200, 204]
    assert data["targets"][1] == {"name": "web", "url": "https://example.com"}


def test_parse_rejects_tabs_and_bad_indent():
    with pytest.raises(ConfigError):
        parse_simple_yaml("a:\n\tb: 1\n")
    with pytest.raises(ConfigError):
        parse_simple_yaml("just a string\n")


def test_load_config_validates(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        "database: my.db\n"
        "targets:\n"
        "  - name: api\n"
        "    url: https://example.com/health\n"
        "    keyword: '\"ok\"'\n"
    )
    loaded = load_config(str(cfg))
    assert loaded.database == "my.db"
    assert len(loaded.targets) == 1
    t = loaded.targets[0]
    assert (t.name, t.interval, t.timeout) == ("api", 60, 10)
    assert t.expected_status == [200]
    assert t.keyword == '"ok"'


def test_load_config_missing_file_gives_defaults():
    loaded = load_config("/nonexistent/path/config.yaml")
    assert loaded.targets == []
    assert loaded.database == "uptimebeacon.db"


def test_load_config_rejects_bad_targets(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("targets:\n  - name: api\n    url: ftp://example.com\n")
    with pytest.raises(ConfigError):
        load_config(str(cfg))
    cfg.write_text("targets:\n  - name: a\n    url: https://x.io\n"
                   "  - name: a\n    url: https://y.io\n")
    with pytest.raises(ConfigError):
        load_config(str(cfg))


def test_dump_and_reload_roundtrip(tmp_path):
    config = AppConfig(database="x.db", targets=[
        Target(name="api", url="https://example.com", interval=30,
               timeout=5, expected_status=[200, 204], keyword="ok"),
        Target(name="web", url="http://example.org"),
    ])
    path = str(tmp_path / "out.yaml")
    save_config(config, path)
    reloaded = load_config(path)
    assert reloaded.database == "x.db"
    assert [t.name for t in reloaded.targets] == ["api", "web"]
    assert reloaded.targets[0].keyword == "ok"
    assert reloaded.targets[0].expected_status == [200, 204]
    assert reloaded.targets[1].keyword is None
