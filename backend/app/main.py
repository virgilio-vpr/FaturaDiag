from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.core.errors import problem_response, register_exception_handlers
from app.core.health import check_dependencies
from app.core.logging import configure_logging
from app.core.settings import Settings

settings = Settings()
configure_logging(settings.log_level)
logger = structlog.get_logger(__name__)

app = FastAPI(title="FaturaDiag")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)

NextHandler = Callable[[Request], Awaitable[Response]]


@app.middleware("http")
async def request_context_middleware(request: Request, call_next: NextHandler) -> Response:
    request_id = str(uuid4())
    started_at = perf_counter()
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            status_code=response.status_code,
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        return response
    finally:
        structlog.contextvars.clear_contextvars()


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", include_in_schema=False, response_model=None)
def ready(request: Request) -> dict[str, object] | Response:
    dependencies = check_dependencies(settings)
    unavailable = [name for name, is_available in dependencies.items() if not is_available]
    if unavailable:
        return problem_response(
            request,
            status_code=503,
            title="Service Unavailable",
            detail="Dependências indisponíveis.",
            errors=[{"dependency": name, "status": "unavailable"} for name in unavailable],
        )
    return {
        "status": "ready",
        "dependencies": {name: "ok" for name in dependencies},
    }
