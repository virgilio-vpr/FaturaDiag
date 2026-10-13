from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: SecretStr = SecretStr("development-only-change-me")
    cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://energydiag:energydiag@localhost:5432/energydiag"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "energydiag"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
