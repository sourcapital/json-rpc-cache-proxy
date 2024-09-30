import time
import json
import uuid
import asyncio
import hashlib
from collections import deque
from contextlib import asynccontextmanager

import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from cache import ChainSpecificTTLCache
from config import config
from utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    # Startup
    proxy.session = aiohttp.ClientSession()
    yield
    # Shutdown
    logger.info("Shutting down JSON-RPC Cache Proxy")
    if proxy.session:
        await proxy.session.close()


app = FastAPI(lifespan=lifespan)


class JSONRPCCacheProxy:
    """
    Handles caching and proxying of JSON-RPC requests to various blockchain nodes.
    """

    def __init__(self):
        self.cache = ChainSpecificTTLCache()
        self.cache_statuses = deque(maxlen=1000)  # Store last 1000 cache statuses for cache ratio calculations
        self.last_ratio_log = time.time()
        self.session = None

    @staticmethod
    def generate_cache_key(chain: str, body: {}) -> str:
        """
        Generate a unique cache key based on the chain and request body.
        """
        body_copy = body.copy()
        body_copy.pop('id', None)
        return hashlib.md5(f"{chain}:{json.dumps(body_copy, sort_keys=True)}".encode()).hexdigest()

    async def handle_http_request(self, chain: str, body: {}, request: Request) -> ({}, str, str):
        """
        Handle an incoming HTTP JSON-RPC request, using cache if possible.
        """
        start_time = time.time()

        if chain not in config.RPC_URL:
            logger.error(f"No RPC endpoint configured for chain: {chain}")
            raise HTTPException(status_code=404, detail="No RPC endpoint configured for this chain")

        cache_key = self.generate_cache_key(chain, body)
        chain_cache = self.cache.get_cache(chain, config.CACHE_TTL[chain])

        cached_response, cache_status = chain_cache.get(cache_key)

        if cache_status == "HIT":
            response = cached_response
            upstream_response_time = ""
        else:
            try:
                async with self.session.post(config.RPC_URL[chain], json=body) as resp:
                    response = await resp.json()

                chain_cache.set(cache_key, response)
                logger.debug(f"Successfully fetched and cached response for chain: {chain}")
                upstream_response_time = f"{(time.time() - start_time) * 1000:.2f}"
            except aiohttp.ClientError as e:
                logger.error(f"Error during http communication with the {chain} RPC: {str(e)}")
                raise HTTPException(status_code=502, detail="Error communicating with node")

        total_time = f"{(time.time() - start_time) * 1000:.2f}"

        logger.info(json.dumps({
            "remote_addr": request.client.host,
            "x_forwarded_for": request.headers.get("X-Forwarded-For", "n/a"),
            "request_body": json.dumps(body),
            "status": "200",
            "upstream_cache_status": cache_status,
            "upstream_response_time": f"{upstream_response_time}ms" if upstream_response_time else "n/a",
            "total_response_time": f"{total_time}ms",
            "cache_key": cache_key,
            "request_uri": request.url.path,
        }))

        self.cache_statuses.append(cache_status)
        self._log_cache_ratio()

        return response, cache_status, cache_key

    def _log_cache_ratio(self):
        now = time.time()
        if now - self.last_ratio_log >= 10:  # Log every 10 seconds
            total_requests = len(self.cache_statuses)
            if total_requests > 0:
                hit_count = self.cache_statuses.count("HIT")
                miss_count = self.cache_statuses.count("MISS")
                expired_count = self.cache_statuses.count("EXPIRED")

                hit_ratio = hit_count / total_requests * 100
                miss_ratio = miss_count / total_requests * 100
                expired_ratio = expired_count / total_requests * 100

                logger.info(
                    f"Cache Ratio (last {total_requests} requests): "
                    f"HIT: {hit_count} ({hit_ratio:.2f}%), "
                    f"MISS: {miss_count} ({miss_ratio:.2f}%), "
                    f"EXPIRED: {expired_count} ({expired_ratio:.2f}%)"
                )

            self.last_ratio_log = now


proxy = JSONRPCCacheProxy()


@app.post("/{chain}")
async def http_endpoint(chain: str, request: Request):
    """
    FastAPI route handler for HTTP JSON-RPC requests.
    """
    body = await request.json()
    response, cache_status, cache_key = await proxy.handle_http_request(chain, body, request)

    # Create a JSONResponse with the additional headers
    return JSONResponse(
        content=response,
        headers={
            "X-Cache-Status": cache_status,
            "X-Cache-Key": cache_key,
        }
    )


@app.websocket("/{chain}/ws")
async def websocket_endpoint(client_ws: WebSocket, chain: str):
    await client_ws.accept()

    connection_closed = asyncio.Event()
    client_id = f"{client_ws.client.host}:{str(uuid.uuid4())}"
    logger.debug(f"Accepted Client<>Proxy websocket connection for {client_id}<>Proxy<>{chain} connection")

    try:
        ws_url = config.get_ws_url(chain)  # This will raise ValueError if WS_URL is not configured

        async with proxy.session.ws_connect(ws_url) as rpc_ws:
            logger.debug(f"Established Proxy<>RPC websocket connection for {client_id}<>Proxy<>{chain} connection")

            async def forward_to_client():
                try:
                    while not connection_closed.is_set():
                        try:
                            message = await asyncio.wait_for(rpc_ws.receive(), timeout=1.0)
                            if message.type == aiohttp.WSMsgType.TEXT:
                                if not connection_closed.is_set():
                                    await client_ws.send_text(message.data)
                            elif message.type == aiohttp.WSMsgType.CLOSE:
                                break
                        except asyncio.TimeoutError:
                            continue
                except Exception as e:
                    if not connection_closed.is_set():
                        logger.error(f"Websocket error for {client_id}<>Proxy<>{chain} connection: {str(e)}")

            async def forward_to_rpc():
                try:
                    while not connection_closed.is_set():
                        try:
                            data = await asyncio.wait_for(client_ws.receive_text(), timeout=1.0)
                            if len(data) > 0:
                                await rpc_ws.send_str(data)

                                logger.info(json.dumps({
                                    "client_id": client_id,
                                    "request_body": data,
                                    "status": "200",
                                    "request_uri": f"/{chain}/ws",
                                    "connection_type": "websocket"
                                }))
                        except asyncio.TimeoutError:
                            continue
                except WebSocketDisconnect:
                    connection_closed.set()
                    logger.debug(f"Closed Proxy<>RPC websocket connection for {client_id}<>Proxy<>{chain} connection")

            # Run both forwarding tasks concurrently
            await asyncio.gather(
                forward_to_client(),
                forward_to_rpc()
            )
    except ValueError as e:
        logger.error(f"WebSocket configuration error for {client_id}<>Proxy<>{chain} connection: {str(e)}")
        await client_ws.close(code=1008, reason=str(e))  # Close with HTTP 404 equivalent
        return
    except Exception as e:
        logger.error(f"Websocket error for {client_id}<>Proxy<>{chain} connection: {str(e)}")
    finally:
        connection_closed.set()
        try:
            await client_ws.close()
        except RuntimeError:
            pass
        logger.debug(f"Closed Client<>Proxy websocket connection for {client_id}<>Proxy<>{chain} connection")


if __name__ == "__main__":
    logger.info(f"Starting JSON-RPC Cache Proxy on {config.HOST}:{config.PORT}")
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level='error',  # This will only show error logs
        access_log=False  # This will disable access logs
    )
