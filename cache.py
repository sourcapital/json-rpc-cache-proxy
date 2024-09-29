import time
from typing import Dict, Tuple, Any
from collections import OrderedDict


class TTLCache:
    """
    A custom Time-To-Live (TTL) cache using OrderedDict.
    Stores key-value pairs with expiration time and supports a maximum size.
    """

    def __init__(self, maxsize: int, ttl: int):
        """
        Initialize the CustomTTLCache.

        :param maxsize: Maximum number of items in the cache.
        :param ttl: Time-to-live for each entry in seconds.
        """
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()

    def get(self, key: str) -> Tuple[Any, str]:
        """
        Retrieve a value from the cache and return its status.

        :param key: The key to look up.
        :return: Tuple of (value, status). Status can be "MISS", "EXPIRED", or "HIT".
        """
        if key not in self.cache:
            return None, "MISS"
        value, expiration_time = self.cache[key]
        if time.time() > expiration_time:
            return value, "EXPIRED"
        self.cache.move_to_end(key)
        return value, "HIT"

    def set(self, key: str, value: Any):
        """
        Set a value in the cache with the configured TTL.

        :param key: The key under which to store the value.
        :param value: The value to be stored.
        """
        if len(self.cache) >= self.maxsize:
            self.cache.popitem(last=False)
        expiration_time = time.time() + self.ttl
        self.cache[key] = (value, expiration_time)
        self.cache.move_to_end(key)


class ChainSpecificTTLCache:
    """
    Manages separate CustomTTLCache instances for different chains.
    """

    def __init__(self, maxsize=1000):
        """
        Initialize the ChainSpecificTTLCache.

        :param maxsize: Maximum size for each individual chain cache.
        """
        self.caches: Dict[str, TTLCache] = {}
        self.maxsize = maxsize

    def get_cache(self, chain: str, ttl: int) -> TTLCache:
        """
        Get or create a CustomTTLCache for a specific chain.

        :param chain: The identifier for the blockchain network.
        :param ttl: Time-to-live for entries in this chain's cache.
        :return: The TTL cache for the specified chain.
        """
        if chain not in self.caches:
            self.caches[chain] = TTLCache(maxsize=self.maxsize, ttl=ttl)
        return self.caches[chain]
