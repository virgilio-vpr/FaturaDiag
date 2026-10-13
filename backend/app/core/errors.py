from collections.abc import Mapping
from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


def problem_response(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str,
    errors: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type="application/problem+json",
        headers=headers,
        content={
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "detail": detail,
            "instance": request.url.path,
            "errors": errors or [],
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exception: StarletteHTTPException
    ) -> JSONResponse:
        try:
            title = HTTPStatus(exception.status_code).phrase
        except ValueError:
            title = "Erro HTTP"
        detail = exception.detail if isinstance(exception.detail, str) else title
        return problem_response(
            request,
            status_code=exception.status_code,
            title=title,
            detail=detail,
            headers=exception.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        errors: list[dict[str, str]] = []
        for error in exception.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            errors.append(
                {
                    "field": location,
                    "message": str(error.get("msg", "Valor inválido.")),
                    "code": str(error.get("type", "validation_error")),
                }
            )
        return problem_response(
            request,
            status_code=422,
            title="Unprocessable Entity",
            detail="A solicitação contém dados inválidos.",
            errors=errors,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exception: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "unhandled_exception",
            request_id=request_id,
            exception_type=type(exception).__name__,
        )
        return problem_response(
            request,
            status_code=500,
            title="Internal Server Error",
            detail="Ocorreu um erro interno.",
        )
