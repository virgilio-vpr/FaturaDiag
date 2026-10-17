from decimal import Decimal
from typing import Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_SECRET_KEY = "development-only-secret-key-change-me-32bytes"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    secret_key: SecretStr = SecretStr(DEVELOPMENT_SECRET_KEY)
    cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://energydiag:energydiag@localhost:5432/energydiag"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    auth_max_failed_attempts: int = 5
    auth_lockout_base_seconds: int = 30
    auth_lockout_max_seconds: int = 3600
    seed_admin_email: str = "admin@example.com"
    seed_admin_password: SecretStr = SecretStr("")
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "energydiag"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    storage_backend: str = "local"
    storage_local_path: str = "./data/storage"
    max_upload_mb: int = 20
    max_pdf_pages: int = 12
    llm_provider: str = "fake"
    llm_model: str = ""
    llm_fallback_provider: str = ""
    llm_fallback_model: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_timeout_s: int = 90
    llm_monthly_budget_brl: Decimal = Decimal(0)
    llm_preco_entrada_brl_por_mtok: Decimal = Decimal(0)
    llm_preco_saida_brl_por_mtok: Decimal = Decimal(0)

    @model_validator(mode="after")
    def validate_production_secret(self) -> Self:
        secret_key = self.secret_key.get_secret_value()
        if self.app_env.casefold() in {"prod", "production"} and (
            secret_key == DEVELOPMENT_SECRET_KEY or len(secret_key) < 32
        ):
            raise ValueError(
                "SECRET_KEY de produção deve ser exclusivo e ter ao menos 32 caracteres."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
