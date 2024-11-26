import time
import json
import uuid
import asyncio
import hashlib
from typing import Union, Dict, List, Tuple
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
    def generate_cache_key(chain: str, body: Union[Dict, List]) -> str:
        """
        Generate a unique cache key based on the chain and request body.
        Supports both single requests and batched requests.
        """
        if isinstance(body, list):
            # For batched requests
            cleaned_bodies = []
            for item in body:
                item_copy = item.copy()
                item_copy.pop('id', None)
                cleaned_bodies.append(json.dumps(item_copy, sort_keys=True))
            cache_key_content = f"{chain}:{':'.join(sorted(cleaned_bodies))}"
        else:
            # For single requests
            body_copy = body.copy()
            body_copy.pop('id', None)
            cache_key_content = f"{chain}:{json.dumps(body_copy, sort_keys=True)}"

        return hashlib.md5(cache_key_content.encode()).hexdigest()

    async def handle_http_request(self, chain: str, request: Request) -> Tuple[Union[Dict, List], str, str]:
        """
        Handle an incoming HTTP JSON-RPC request, using cache if possible.
        Supports both single requests and batched requests.
        """
        rpc_request = await request.json()

        start_time = time.time()
        upstream_start_time = None
        upstream_end_time = None

        if chain not in config.RPC_URL:
            logger.error(f"No RPC endpoint configured for chain: {chain}")
            raise HTTPException(status_code=404, detail="No RPC endpoint configured for this chain")

        chain_specific_cache = self.cache.get_cache(chain, config.CACHE_TTL[chain])

        async def process_single_request(rpc_request: Dict) -> Tuple[Dict, str, str, Dict]:
            cache_key = self.generate_cache_key(chain, rpc_request)
            cached_response, cache_status = chain_specific_cache.get(cache_key)
            if cache_status == "HIT":
                response = cached_response.copy()
                response['id'] = rpc_request.get('id')
                return response, cache_status, cache_key, None
            else:
                return None, cache_status, cache_key, rpc_request

        async def fetch_from_rpc(rpc_request: Union[Dict, List]) -> Union[Dict, List]:
            nonlocal upstream_start_time, upstream_end_time
            try:
                upstream_start_time = time.time()
                async with self.session.post(config.RPC_URL[chain], json=rpc_request) as response:
                    result = json.loads(await response.text())
                upstream_end_time = time.time()
                return result
            except aiohttp.ClientError as error:
                logger.error(f"Error during HTTP communication with the {chain} RPC: {str(error)}")
                raise HTTPException(status_code=502, detail="Error communicating with node")

        if isinstance(rpc_request, list):
            batch_response, overall_cache_status, batch_request, cache_key_map = [], "HIT", [], {}

            for sub_request in rpc_request:
                sub_response, sub_cache_status, sub_cache_key, sub_request_to_send = await process_single_request(sub_request)
                if sub_request_to_send:
                    cache_key_map[sub_request_to_send['id']] = sub_cache_key
                    batch_request.append(sub_request_to_send)
                if sub_response:
                    batch_response.append(sub_response)
                if sub_cache_status != "HIT":
                    overall_cache_status = "MISS" if sub_cache_status == "MISS" else "EXPIRED"

            if batch_request:
                rpc_response = await fetch_from_rpc(batch_request)
                for sub_response in rpc_response:
                    sub_cache_key = cache_key_map[sub_response['id']]
                    chain_specific_cache.set(sub_cache_key, sub_response)
                    batch_response.append(sub_response)

            batch_cache_key = self.generate_cache_key(chain, rpc_request)
            final_response, final_cache_status, final_cache_key = batch_response, overall_cache_status, batch_cache_key
        else:
            single_response, single_cache_status, single_cache_key, single_request = await process_single_request(rpc_request)

            if single_request:
                single_response = await fetch_from_rpc(rpc_request)
                chain_specific_cache.set(single_cache_key, single_response)

            final_response, final_cache_status, final_cache_key = single_response, single_cache_status, single_cache_key

        total_request_time = (time.time() - start_time)
        upstream_time = (upstream_end_time - upstream_start_time) if upstream_start_time and upstream_end_time else None

        logger.info(json.dumps({
            "remote_addr": request.client.host,
            "x_forwarded_for": request.headers.get("X-Forwarded-For", "n/a"),
            "request_body": json.dumps(rpc_request),
            "status": "200",
            "upstream_cache_status": final_cache_status,
            "upstream_response_time": f"{upstream_time * 1e3:.2f}ms" if upstream_time else "n/a",
            "total_response_time": f"{total_request_time * 1e3:.2f}ms",
            "cache_key": final_cache_key,
            "request_uri": request.url.path,
        }))

        self.cache_statuses.append(final_cache_status)
        self._log_cache_ratio()

        return final_response, final_cache_status, final_cache_key

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
    response, cache_status, cache_key = await proxy.handle_http_request(chain, request)

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
