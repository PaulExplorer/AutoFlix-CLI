from autoflix_cli.config_loader import (
    strip_json_comments,
    strip_trailing_commas,
    load_config,
)


def test_strip_json_comments():
    raw = """
    {
        // line comment
        "a": 1, /* block
        comment */
        "b": "http://not-a-comment.com", // trailing
    }
    """
    cleaned = strip_json_comments(raw)
    assert "//" not in cleaned.replace("http://", "")
    assert "/*" not in cleaned


def test_strip_trailing_commas():
    assert strip_trailing_commas('{"a": 1,}') == '{"a": 1}'
    assert strip_trailing_commas("[1, 2,]") == "[1, 2]"


def test_load_config_precedence(monkeypatch):
    import autoflix_cli.config_loader as cl

    monkeypatch.setattr(
        cl, "load_remote_jsonc", lambda url, default: {"a": 2, "b": {"x": 2}}
    )
    monkeypatch.setattr(
        cl, "load_local_jsonc", lambda path, default=None: {"b": {"y": 3}}
    )

    config = load_config(
        "https://example.com/config.jsonc",
        {"a": 1, "b": {"x": 1, "z": 1}, "c": 3},
        "/some/local.jsonc",
    )

    # local overrides remote at the top level (shallow), remote overrides
    # default, and the merged result deep-merges with the defaults.
    assert config == {"a": 2, "b": {"x": 1, "z": 1, "y": 3}, "c": 3}


def test_load_config_without_local(monkeypatch):
    import autoflix_cli.config_loader as cl

    monkeypatch.setattr(cl, "load_remote_jsonc", lambda url, default: {"a": 2})
    config = load_config("https://example.com/c.jsonc", {"a": 1, "b": 9})
    assert config == {"a": 2, "b": 9}
