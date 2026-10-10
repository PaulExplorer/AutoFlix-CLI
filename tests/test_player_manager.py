import json
import urllib.parse

from autoflix_cli import player_manager as pm
from autoflix_cli import proxy
from autoflix_cli.scraping import player


def test_guess_subtitle_ext():
    assert pm._guess_subtitle_ext("https://x.com/a.srt") == ".srt"
    assert pm._guess_subtitle_ext("https://x.com/a.ass") == ".ass"
    assert pm._guess_subtitle_ext("https://x.com/a.vtt.xz") == ".vtt"
    assert pm._guess_subtitle_ext("https://x.com/a.xz") == ".srt"
    assert pm._guess_subtitle_ext("https://x.com/noext") == ".srt"


def test_build_upstream_headers():
    headers = {"User-Agent": "ua"}
    config = {
        "alt-used": True,
        "sec_headers": "A: 1;B: 2",
    }
    built = pm._build_upstream_headers(headers, "https://ref.com/", config, "ref.com")
    assert built == {
        "User-Agent": "ua",
        "Referer": "https://ref.com/",
        "Alt-Used": "ref.com",
        "A": "1",
        "B": "2",
    }


def test_build_upstream_headers_without_optional_values():
    built = pm._build_upstream_headers({}, "", {}, "ref.com")
    assert built == {}


def test_build_proxy_url_format(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    proxy_headers = {"Referer": "https://ref.com/"}

    url = pm._build_proxy_url(
        "https://cdn.example.com/seg.m3u8", proxy_headers, {}, False
    )
    expected = (
        "http://127.0.0.1:9999/stream"
        f"?url={urllib.parse.quote('https://cdn.example.com/seg.m3u8')}"
        f"&headers={urllib.parse.quote(json.dumps(proxy_headers))}"
    )
    assert url == expected


def test_build_proxy_url_endpoint_selection(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    base = "https://cdn.example.com/seg.mp4"

    mp4_url = pm._build_proxy_url(base, {}, {"ext": "mp4"}, False)
    assert mp4_url.split("?")[0].endswith("/video")
    direct_mp4 = pm._build_proxy_url(base, {}, {}, True)
    assert direct_mp4.split("?")[0].endswith("/video")
    hls = pm._build_proxy_url(base, {}, {}, False)
    assert hls.split("?")[0].endswith("/stream")


def test_build_proxy_url_without_proxy(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", None)
    assert pm._build_proxy_url("https://x.com/f", {}, {}, False) is None


def test_resolve_stream_direct(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", None)
    assert pm._resolve_stream("https://x.com/f.mp4", {}, True) == (
        "https://x.com/f.mp4",
        None,
    )


def test_embed_domain_from_embed_url():
    assert pm._embed_domain("https://Uqload.vc/embed-1.html") == "uqload.vc"


def test_embed_domain_falls_back_to_stream_for_shorthand():
    # Shorthand embeds (montmyoboky:535) carry no host; the stream does.
    assert (
        pm._embed_domain("montmyoboky:535", "https://cdn.montmyoboku.net/a/master.m3u8")
        == "cdn.montmyoboku.net"
    )


def test_embed_domain_without_any_host():
    assert pm._embed_domain("netu:abc123") == ""


def test_embed_domain_ignores_bare_word_host():
    # "https://x" has no dotted host, so the stream host is the reliable one.
    assert pm._embed_domain("https://x", "https://cdn.tld/a.m3u8") == "cdn.tld"


def test_config_for_resolved_keeps_mp4_declared_ext():
    config, is_mp4 = pm._config_for_resolved({"ext": "mp4"}, "mp4")
    assert (config["ext"], is_mp4) == ("mp4", True)


def test_config_for_resolved_overrides_mp4_ext_on_playlist():
    # uqload is declared ext:mp4 but answers with an HLS master.
    config, is_mp4 = pm._config_for_resolved({"ext": "mp4"}, "hls_master")
    assert (config["ext"], is_mp4) == ("hls", False)


def test_config_for_resolved_keeps_other_keys():
    config, _ = pm._config_for_resolved(
        {"ext": "mp4", "sec_headers": "A: b"}, "hls_master"
    )
    assert config["sec_headers"] == "A: b"


def test_config_for_resolved_does_not_mutate_input():
    original = {"ext": "mp4"}
    pm._config_for_resolved(original, "hls_master")
    assert original == {"ext": "mp4"}


def test_resolve_launch_mode_defaults_to_proxy():
    # Existing configs without any mode key must keep using the proxy.
    assert pm.resolve_launch_mode({}, "mpv") == "proxy"
    assert pm.resolve_launch_mode(None, "vlc") == "proxy"
    assert pm.resolve_launch_mode({"type": "default"}, "mpv") == "proxy"


def test_resolve_launch_mode_legacy_key():
    assert pm.resolve_launch_mode({"mode": "direct"}, "mpv") == "direct"
    assert pm.resolve_launch_mode({"mode": "proxy"}, "mpv") == "proxy"


def test_resolve_launch_mode_per_player():
    config = {"modes": {"mpv": "direct", "vlc": "proxy"}}
    assert pm.resolve_launch_mode(config, "mpv") == "direct"
    assert pm.resolve_launch_mode(config, "vlc") == "proxy"
    # Not listed -> legacy key -> default
    assert pm.resolve_launch_mode({"modes": {"mpv": "direct"}}, "vlc") == "proxy"
    # Per-player entry wins over the legacy global key
    config = {"mode": "direct", "modes": {"mpv": "proxy"}}
    assert pm.resolve_launch_mode(config, "mpv") == "proxy"
    assert pm.resolve_launch_mode(config, "vlc") == "direct"


def test_resolve_launch_mode_browser_is_proxy_only():
    # A browser cannot carry a Referer on the upstream request.
    assert pm.resolve_launch_mode({"modes": {"browser": "direct"}}, "browser") == (
        "proxy"
    )


def test_resolve_launch_mode_invalid_falls_back_to_proxy():
    assert pm.resolve_launch_mode({"mode": "dirtect"}, "mpv") == "proxy"
    assert pm.resolve_launch_mode({"modes": {"mpv": True}}, "mpv") == "proxy"


def test_build_direct_headers_comma_separated():
    config = {"alt-used": True, "sec_headers": "A: 1;B: 2"}
    built = pm._build_direct_headers(
        {"User-Agent": "ua"}, "https://ref.com/page", config, "ref.com"
    )
    pairs = dict(item.split(": ", 1) for item in built.split(","))
    assert pairs["Origin"] == "https://ref.com"
    assert "Referer" not in pairs  # passed via --referrer
    assert "User-Agent" not in pairs  # passed via --user-agent
    assert pairs["Alt-Used"] == "ref.com"
    assert pairs["A"] == "1"
    assert pairs["B"] == "2"
    assert "Sec-Fetch-Dest" not in pairs


def test_build_direct_headers_default_sec_headers():
    built = pm._build_direct_headers({}, "https://ref.com/", {}, "ref.com")
    pairs = dict(item.split(": ", 1) for item in built.split(","))
    assert pairs["Sec-Fetch-Dest"] == "iframe"
    assert pairs["Sec-Fetch-Mode"] == "navigate"
    assert pairs["Sec-Fetch-Site"] == "same-origin"
    assert pairs["Origin"] == "https://ref.com"


def test_build_direct_headers_sec_headers_true():
    config = {"sec_headers": True}
    built = pm._build_direct_headers({}, "https://ref.com/", config, "ref.com")
    assert "Sec-Fetch-Dest: iframe" in built


def test_build_direct_headers_no_header():
    config = {"no-header": True, "alt-used": True}
    assert pm._build_direct_headers({"User-Agent": "ua"}, "https://ref.com/", config, "ref.com") == ""


def test_build_direct_headers_without_referer():
    # Must not raise: a direct URL may carry no Referer at all.
    built = pm._build_direct_headers({}, "", {}, "")
    assert "Origin" not in built


def test_origin_from_referer():
    assert pm._origin_from_referer("https://a.com/x?y=1") == "https://a.com"
    assert pm._origin_from_referer("http://a.com:8080/") == "http://a.com:8080"
    assert pm._origin_from_referer("") == ""
    assert pm._origin_from_referer("not a url") == ""


def test_compute_referer():
    config = {"referrer": "full"}
    assert (
        pm._compute_referer("https://e.com/embed", {}, config, "e.com", False)
        == "https://e.com/embed/"
    )
    # An already complete URL is left untouched
    assert (
        pm._compute_referer("https://e.com/embed/", {}, config, "e.com", False)
        == "https://e.com/embed/"
    )
    config = {"referrer": "path"}
    assert pm._compute_referer("https://e.com/a/b", {}, config, "e.com", False) == (
        "https://e.com/"
    )
    config = {"referrer": "https://other.com/"}
    assert pm._compute_referer("https://e.com/a", {}, config, "e.com", False) == (
        "https://other.com/"
    )
    # No referrer setting -> domain root
    assert pm._compute_referer("https://e.com/a", {}, {}, "e.com", False) == (
        "https://e.com/"
    )
    # Direct URLs reuse the header provided by the caller
    assert pm._compute_referer(
        "https://cdn/f.m3u8", {"Referer": "https://e.com/"}, {}, "cdn", True
    ) == "https://e.com/"


def test_build_direct_command_mpv():
    cmd = pm._build_direct_command(
        "https://cdn/f.m3u8",
        {"User-Agent": "ua"},
        {"referrer": "https://e.com/"},
        "https://e.com/",
        "e.com",
        "mpv",
        "/usr/bin/mpv",
        "My Title",
        ["/tmp/sub.srt"],
    )
    assert cmd[0] == "/usr/bin/mpv"
    assert "--referrer=https://e.com/" in cmd
    assert "--user-agent=ua" in cmd
    assert any(c.startswith("--http-header-fields=Origin: https://e.com") for c in cmd)
    assert "--title=My Title" in cmd
    assert "--sub-file=/tmp/sub.srt" in cmd
    # Direct playback is more resilient than the bare default
    assert any(c.startswith("--stream-lavf-o=reconnect_streamed=1") for c in cmd)
    # These retry every clean EOF and stall playback with "End of file" logs
    joined = " ".join(cmd)
    assert "reconnect_at_eof" not in joined
    assert "reconnect=1" not in joined
    # The URL is always the last argument
    assert cmd[-1] == "https://cdn/f.m3u8"


def test_build_direct_command_mpv_options():
    config = {"mpv_options": ["--tls-verify=no", "--demuxer-max-bytes=64MiB"]}
    cmd = pm._build_direct_command(
        "https://cdn/f.m3u8", {}, config, "", "cdn", "mpv", "mpv", "T", []
    )
    assert "--tls-verify=no" in cmd
    assert "--demuxer-max-bytes=64MiB" in cmd


def test_build_direct_command_vlc():
    cmd = pm._build_direct_command(
        "https://cdn/f.mp4",
        {"User-Agent": "ua"},
        {},
        "https://e.com/",
        "e.com",
        "vlc",
        "/usr/bin/vlc",
        "T",
        [],
    )
    assert ":http-referrer=https://e.com/" in cmd
    assert ":http-user-agent=ua" in cmd
    assert "--meta-title=T" in cmd
    assert cmd[-1] == "https://cdn/f.mp4"


def test_build_proxy_command(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    cmd = pm._build_proxy_command(
        "https://cdn/f.m3u8",
        {"User-Agent": "ua"},
        {},
        "https://e.com/",
        "e.com",
        False,
        "mpv",
        "mpv",
        "T",
        ["/tmp/sub.srt"],
    )
    assert cmd[0] == "mpv"
    assert cmd[1].startswith("http://127.0.0.1:9999/stream?url=")
    assert "--title=T" in cmd
    assert "--sub-file=/tmp/sub.srt" in cmd


def test_build_proxy_command_without_proxy(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", None)
    assert (
        pm._build_proxy_command(
            "https://cdn/f.m3u8", {}, {}, "", "cdn", False, "mpv", "mpv", "T", []
        )
        is None
    )


def test_build_browser_player_url(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    url = pm._build_browser_player_url(
        "https://cdn/f.m3u8", {}, {}, "https://e.com/", "e.com", False, None
    )
    assert url.startswith("http://127.0.0.1:9999/player?url=")
    assert "sub_path" not in url


def test_build_browser_player_url_without_proxy(monkeypatch):
    monkeypatch.setattr(proxy, "PROXY_URL", None)
    assert (
        pm._build_browser_player_url(
            "https://cdn/f.m3u8", {}, {}, "", "cdn", False, None
        )
        is None
    )


def test_get_player_modes():
    assert pm.get_player_modes("mpv") == ("proxy", "direct")
    assert pm.get_player_modes("browser") == ("proxy",)
    assert pm.get_player_modes("unknown") == ("proxy",)


def test_launch_player_dispatches_to_requested_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(proxy, "PROXY_URL", "http://127.0.0.1:9999")
    monkeypatch.setattr(
        pm, "_get_player_executable", lambda code: f"/usr/bin/{code}"
    )
    monkeypatch.setattr(
        pm,
        "_play_direct",
        lambda *a, **kw: calls.append(("direct", a[5])) or True,
    )
    monkeypatch.setattr(
        pm,
        "_play_via_proxy",
        lambda *a, **kw: calls.append(("proxy", a[6])) or True,
    )
    monkeypatch.setattr(
        pm, "_play_in_browser", lambda *a, **kw: calls.append(("browser", None)) or True
    )

    kwargs = dict(
        stream_url="https://cdn/f.m3u8",
        headers={},
        player_config={},
        is_mp4=False,
        referer="https://e.com/",
        domain="e.com",
        title="T",
        subtitle_paths=[],
    )
    pm._launch_player(player_code="mpv", mode="direct", **kwargs)
    pm._launch_player(player_code="mpv", mode="proxy", **kwargs)
    pm._launch_player(player_code="browser", mode="proxy", **kwargs)

    assert calls == [("direct", "mpv"), ("proxy", "mpv"), ("browser", None)]


def test_launch_player_unknown_mode():
    assert (
        pm._launch_player(
            stream_url="https://cdn/f.m3u8",
            headers={},
            player_config={},
            player_code="mpv",
            mode="nope",
            is_mp4=False,
            referer="",
            domain="cdn",
            title="T",
            subtitle_paths=[],
        )
        is False
    )


def test_devtest_candidates_cover_every_mode():
    from autoflix_cli.handlers.devtest import _launch_candidates

    candidates = _launch_candidates({})
    assert set(candidates) == {
        ("mpv", "proxy"),
        ("mpv", "direct"),
        ("vlc", "proxy"),
        ("vlc", "direct"),
        ("browser", "proxy"),
    }
    # A browser is never offered in direct mode
    assert ("browser", "direct") not in candidates


def test_devtest_candidates_put_current_mode_first():
    from autoflix_cli.handlers.devtest import _launch_candidates

    candidates = _launch_candidates({"modes": {"mpv": "direct"}})
    assert candidates[0] == ("mpv", "direct")


def test_match_player_config():
    config = player.players["vidoza"]
    assert pm._match_player_config("https://vidoza.stream/e/abc") == (
        config,
        "vidoza",
    )
    assert pm._match_player_config("https://unknown-host.tld/e") == ({}, "")
