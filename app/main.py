from .logging_config import configure_logging

configure_logging()

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from . import config
from .database import engine
from .models import Base
from .rate_limit import limiter
from .routers import meta_auth, meta_webhook, payments, requests, services, social_media

logger = logging.getLogger(__name__)

app = FastAPI()

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

allowed_origins = ["http://localhost:4200"]
if config.ALLOWED_ORIGIN:
    allowed_origins.append(config.ALLOWED_ORIGIN)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    Base.metadata.create_all(bind=engine)
except Exception:
    logger.exception("Failed to create/verify database tables at startup")
    raise


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(
        "Validation error on %s %s: %s",
        request.method,
        request.url.path,
        exc.errors(),
    )

    errors = []

    for error in exc.errors():
        clean_error = {
            key: value
            for key, value in error.items()
            if key != "ctx"
        }
        errors.append(clean_error)

    return JSONResponse(
        status_code=422,
        content={"detail": errors},
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning("HTTPException on %s %s: %s %s", request.method, request.url.path, exc.status_code, exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    logger.warning("Rate limit exceeded on %s %s: %s", request.method, request.url.path, exc.detail)
    response = JSONResponse(status_code=429, content={"detail": "Too many requests, please try again later"})
    response.headers["Retry-After"] = "60"
    return response


app.include_router(social_media.router)
app.include_router(services.router)
app.include_router(requests.router)
app.include_router(meta_auth.router)
app.include_router(meta_webhook.router)
app.include_router(payments.router)
