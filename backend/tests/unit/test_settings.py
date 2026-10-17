import pytest
from app.core.settings import DEVELOPMENT_SECRET_KEY, Settings
from pydantic import SecretStr, ValidationError


@pytest.mark.parametrize(
    "secret_key",
    [DEVELOPMENT_SECRET_KEY, "short-production-secret"],
)
def test_production_rejects_weak_or_development_secret(secret_key: str) -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="production", secret_key=SecretStr(secret_key))


def test_production_accepts_a_unique_strong_secret() -> None:
    settings = Settings(app_env="production", secret_key=SecretStr("a" * 40))

    assert settings.app_env == "production"
