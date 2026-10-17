from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from starlette.responses import Response

from app.core.errors import problem_response, register_exception_handlers
from app.core.health import check_dependencies
from app.core.logging import configure_logging
from app.core.settings import Settings
from app.modules.auth.router import limiter, rate_limit_problem
from app.modules.auth.router import router as auth_router
from app.modules.clientes.router import router as clientes_router
from app.modules.diagnosticos.router import router as diagnosticos_router
from app.modules.faturas.router import router as faturas_router
from app.modules.medicoes.router import router as medicoes_router
from app.modules.relatorios.router import router as relatorios_router
from app.modules.tarifas.hints_router import router as hints_router
from app.modules.tarifas.parametros_router import router as parametros_router
from app.modules.unidades.router import router as unidades_router

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
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_problem)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(clientes_router, prefix="/api/v1")
app.include_router(unidades_router, prefix="/api/v1")
app.include_router(parametros_router, prefix="/api/v1")
app.include_router(hints_router, prefix="/api/v1")
app.include_router(faturas_router, prefix="/api/v1")
app.include_router(medicoes_router, prefix="/api/v1")
app.include_router(diagnosticos_router, prefix="/api/v1")
app.include_router(relatorios_router, prefix="/api/v1")

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
