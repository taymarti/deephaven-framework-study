"""
`dh-desk-web`: serve the bundled React trader app, and reverse-proxy the paths Deephaven's JS API
uses to the Deephaven server, so the browser talks to ONE origin (no CORS, one port to expose).

    dh-desk-web                                         # http://localhost:4010 -> Deephaven at :10000
    dh-desk-web --port 8080 --dh-url http://dh-host:10000

Proxied to Deephaven (HTTP and websockets):
    /jsapi/*        the JS API module (dh-core.js) the React app imports at runtime
    /js-plugins/*   plugin manifest
    /arrow.*        Arrow Flight / Barrage over gRPC-web
    /io.deephaven.* Deephaven's gRPC-web services
Everything else is the React build (single-page app: unknown paths fall back to index.html).
"""
import argparse
import asyncio
import logging

import aiohttp
from aiohttp import web

from dh_desk.resources import web_root

log = logging.getLogger("dh_desk.web")
_PROXY_PREFIXES = ("/jsapi/", "/js-plugins/", "/arrow.", "/io.deephaven.")
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
               "transfer-encoding", "upgrade", "host", "content-length"}


def make_app(dh_url: str) -> web.Application:
    root = web_root()
    app = web.Application()
    app["dh_url"] = dh_url.rstrip("/")

    async def on_startup(a):
        a["client"] = aiohttp.ClientSession(auto_decompress=False, timeout=aiohttp.ClientTimeout(total=None))

    async def on_cleanup(a):
        await a["client"].close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    async def handle(request: web.Request) -> web.StreamResponse:
        path = request.path
        if path.startswith(_PROXY_PREFIXES):
            if request.headers.get("Upgrade", "").lower() == "websocket":
                return await _proxy_ws(request)
            return await _proxy_http(request)
        target = (root / path.lstrip("/")).resolve()
        if path != "/" and target.is_file() and root in target.parents:
            return web.FileResponse(target)
        return web.FileResponse(root / "index.html")  # SPA fallback

    app.router.add_route("*", "/{tail:.*}", handle)
    return app


async def _proxy_http(request: web.Request) -> web.StreamResponse:
    """Stream the request to Deephaven and the response back (gRPC-web responses are streams)."""
    url = request.app["dh_url"] + request.rel_url.path_qs
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = request.content if request.can_read_body else None
    async with request.app["client"].request(request.method, url, headers=headers, data=body,
                                             allow_redirects=False) as upstream:
        resp = web.StreamResponse(status=upstream.status, reason=upstream.reason,
                                  headers={k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP})
        await resp.prepare(request)
        async for chunk in upstream.content.iter_any():
            await resp.write(chunk)
        await resp.write_eof()
        return resp


async def _proxy_ws(request: web.Request) -> web.WebSocketResponse:
    """Relay a websocket (the JS API's streaming transport) frame by frame in both directions."""
    protocols = [p.strip() for p in request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()]
    url = request.app["dh_url"].replace("http", "ws", 1) + request.rel_url.path_qs
    headers = {k: v for k, v in request.headers.items()
               if k.lower() in ("authorization", "cookie") or k.lower().startswith("x-")}
    async with request.app["client"].ws_connect(url, protocols=protocols, headers=headers, max_msg_size=0) as up:
        down = web.WebSocketResponse(protocols=[up.protocol] if up.protocol else (), max_msg_size=0)
        await down.prepare(request)

        async def pump(src, dst):
            async for msg in src:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    await dst.send_bytes(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    await dst.send_str(msg.data)
                else:
                    break
            await dst.close()

        await asyncio.gather(pump(down, up), pump(up, down), return_exceptions=True)
        return down


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="dh-desk-web", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=4010)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--dh-url", default="http://localhost:10000", help="the dh-desk-server to proxy to")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(f"dh-desk web: http://{args.host}:{args.port}  (Deephaven at {args.dh_url})", flush=True)
    web.run_app(make_app(args.dh_url), host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
