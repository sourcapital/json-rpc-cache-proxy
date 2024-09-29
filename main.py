import time
import json
import hashlib
from contextlib import asynccontextmanager
from typing import Dict, Any
from collections import deque

import uvicorn
import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from config import config
from utils.logger import logger
from cache import ChainSpecificTTLCache


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
        self.session = None
        self.cache = ChainSpecificTTLCache()
        self.cache_statuses = deque(maxlen=1000)  # Store last 1000 requests
        self.last_ratio_log = time.time()

    @staticmethod
    def generate_cache_key(chain: str, body: Dict[str, Any]) -> str:
        """
        Generate a unique cache key based on the chain and request body.
        """
        body_copy = body.copy()
        body_copy.pop('id', None)
        return hashlib.md5(f"{chain}:{json.dumps(body_copy, sort_keys=True)}".encode()).hexdigest()

    async def handle_request(self, chain: str, body: Dict[str, Any], request: Request) -> Dict[str, Any]:
        """
        Handle an incoming JSON-RPC request, using cache if possible.
        """
        start_time = time.time()

        if chain not in config.RPC_URL:
            logger.error(f"No RPC endpoint url configured for chain: {chain}")
            raise HTTPException(status_code=404, detail="No RPC endpoint url configured for this chain")

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
                logger.error(f"Error fetching from RPC node for chain {chain}: {str(e)}")
                raise HTTPException(status_code=502, detail="Error communicating with RPC node")

        total_time = f"{(time.time() - start_time) * 1000:.2f}"

        logger.info(json.dumps({
            "remote_addr": request.client.host,
            "x_forwarded_for": request.headers.get("X-Forwarded-For", ""),
            "request_uri": request.url.path,
            "request_body": json.dumps(body),
            "status": "200",
            "upstream_cache_status": cache_status,
            "upstream_response_time": f"{upstream_response_time}ms" if upstream_response_time else "",
            "total_response_time": f"{total_time}ms",
            "cache_key": cache_key
        }))

        self.cache_statuses.append(cache_status)
        self._log_cache_ratio()

        return response, cache_status

    def _log_cache_ratio(self):
        now = time.time()
        if now - self.last_ratio_log >= 10:  # Log every 10+ seconds
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
                    f"HIT: {hit_ratio:.2f}%, "
                    f"MISS: {miss_ratio:.2f}%, "
                    f"EXPIRED: {expired_ratio:.2f}%"
                )

            self.last_ratio_log = now


proxy = JSONRPCCacheProxy()


@app.post("/{chain}")
async def handle_rpc_request(chain: str, request: Request):
    """
    FastAPI route handler for JSON-RPC requests.
    """
    body = await request.json()
    cache_key = proxy.generate_cache_key(chain, body)
    response, cache_status = await proxy.handle_request(chain, body, request)

    # Create a JSONResponse with the additional headers
    return JSONResponse(
        content=response,
        headers={
            "X-Cache-Status": cache_status,
            "X-Cache-Key": cache_key,
        }
    )


if __name__ == "__main__":
    logger.info(f"Starting JSON-RPC Cache Proxy on {config.HOST}:{config.PORT}")
    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level='error',  # This will only show error logs
        access_log=False  # This will disable access logs
    )
