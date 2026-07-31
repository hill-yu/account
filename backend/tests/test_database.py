from app.database import _connect_args


def test_sqlite_connection_waits_for_concurrent_writer() -> None:
    assert _connect_args("sqlite:///control_plane.db") == {
        "check_same_thread": False,
        "timeout": 60,
    }


def test_non_sqlite_connection_has_no_sqlite_options() -> None:
    assert _connect_args("postgresql://example") == {}
