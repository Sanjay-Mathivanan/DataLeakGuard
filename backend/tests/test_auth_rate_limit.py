import time

import pytest
from limits import parse
from pydantic import ValidationError

from app.core.auth_rate_limit import _build_limiter
from app.core.config import Settings


def test_rate_limit_storage_configuration_accepts_memory_uri():
    settings = Settings(
        _env_file=None,
        AUTH_RATE_LIMIT_STORAGE_URI="memory://",
    )

    assert settings.AUTH_RATE_LIMIT_STORAGE_URI == "memory://"


@pytest.mark.parametrize("storage_uri", ["", "unknown://backend"])
def test_rate_limit_storage_configuration_rejects_unavailable_uri(storage_uri):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            AUTH_RATE_LIMIT_STORAGE_URI=storage_uri,
        )


def test_configured_limiter_enforces_and_expires_a_moving_window():
    storage, limiter = _build_limiter("memory://")
    limit = parse("1/second")

    assert limiter.hit(limit, "auth:test:127.0.0.1")
    assert not limiter.hit(limit, "auth:test:127.0.0.1")
    time.sleep(1.1)
    assert limiter.hit(limit, "auth:test:127.0.0.1")

    storage.reset()
