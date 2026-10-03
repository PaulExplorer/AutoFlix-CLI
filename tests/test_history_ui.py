from autoflix_cli.history_ui import format_history_entry


def test_coflix_regular_episode_strips_series_name():
    entry = {
        "provider": "Coflix",
        "series_title": "Show",
        "season_title": "Show - Season 2",
        "episode_title": "Episode 3",
    }
    assert format_history_entry(entry) == "Show - Season 2 - Episode 3"


def test_coflix_movie():
    assert (
        format_history_entry(
            {
                "provider": "Coflix",
                "series_title": "Show",
                "season_title": "Movie",
                "episode_title": "Movie",
            }
        )
        == "Show (Movie)"
    )


def test_french_stream_hides_season():
    assert (
        format_history_entry(
            {
                "provider": "French-Stream",
                "series_title": "Show",
                "season_title": "Season 1",
                "episode_title": "E1",
            }
        )
        == "Show - E1"
    )


def test_goldenanime_always_series_episode():
    assert (
        format_history_entry(
            {
                "provider": "GoldenAnime",
                "series_title": "Show",
                "season_title": "Season 1",
                "episode_title": "E1",
            }
        )
        == "Show - E1"
    )


def test_goldenms_keeps_season():
    assert (
        format_history_entry(
            {
                "provider": "GoldenMS",
                "series_title": "Show",
                "season_title": "Season 1",
                "episode_title": "E1",
            }
        )
        == "Show - Season 1 - E1"
    )


def test_unknown_provider_falls_back_to_full_path():
    assert (
        format_history_entry(
            {
                "provider": "ArkAnime",
                "series_title": "Show",
                "season_title": "Season 1",
                "episode_title": "E1",
            }
        )
        == "Show - Season 1 - E1"
    )


def test_missing_keys_do_not_crash():
    assert format_history_entry({}) == " -  - "
