import anyio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, PlainTextResponse
from starlette.routing import Route

from mcp_server import mcp


def add_closed_stream_exception_handler(app: Starlette) -> Starlette:
    async def _ignore_closed_stream(_: Request, exc: Exception) -> Response:
        if isinstance(exc, (anyio.ClosedResourceError, anyio.BrokenResourceError)):
            return Response(status_code=204)
        raise exc

    app.add_exception_handler(anyio.ClosedResourceError, _ignore_closed_stream)
    app.add_exception_handler(anyio.BrokenResourceError, _ignore_closed_stream)
    return app


async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


base_app = add_closed_stream_exception_handler(mcp.streamable_http_app())
base_app.router.routes.extend([
    Route("/", healthz, methods=["GET"]),
    Route("/healthz", healthz, methods=["GET"]),
])
app = base_app