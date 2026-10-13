from urllib.error import URLError
from urllib.request import urlopen

import psycopg

from app.core.settings import Settings


def check_database(settings: Settings) -> bool:
    database_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error:
        return False
    return True


def check_storage(settings: Settings) -> bool:
    health_url = f"{settings.s3_endpoint_url.rstrip('/')}/health"
    try:
        with urlopen(health_url, timeout=2) as response:
            return bool(response.status == 200)
    except (OSError, TimeoutError, URLError):
        return False


def check_dependencies(settings: Settings) -> dict[str, bool]:
    return {
        "database": check_database(settings),
        "storage": check_storage(settings),
    }
