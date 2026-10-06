import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest

from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    app.state.limiter.reset()
    yield
