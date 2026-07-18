from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)

_TITLES = {
    400: "Ungültige Anfrage",
    401: "Nicht autorisiert",
    404: "Nicht gefunden",
    409: "Konflikt",
    422: "Validierungsfehler",
    423: "Ressource gesperrt",
    500: "Interner Fehler",
    502: "Externe Quelle fehlgeschlagen",
}


def _problem(status_code: int, detail: str, type_: str, errors: list | None = None) -> JSONResponse:
    body = {"type": type_, "title": _TITLES.get(status_code, "Fehler"), "detail": detail}
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(status_code=status_code, content=body)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem(422, "Eingabe ungültig", "validation_error", errors=exc.errors())

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return _problem(exc.status_code, str(exc.detail), "http_error")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return _problem(500, "Unerwarteter Fehler", "internal_error")
