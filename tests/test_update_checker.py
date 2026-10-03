from autoflix_cli.update_checker import _version_tuple


def test_version_tuple():
    assert _version_tuple("0.9.0") == (0, 9, 0)
    assert _version_tuple("1.10.2") == (1, 10, 2)


def test_version_tuple_ignores_suffixes():
    assert _version_tuple("1.0.0b1") == (1, 0, 0, 1)


def test_version_comparison():
    assert _version_tuple("0.9.0") < _version_tuple("0.10.0")
    assert _version_tuple("1.0.0") > _version_tuple("0.9.9")
