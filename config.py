import os
from typing import Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_env(key: str, default: str = None) -> str:
    return os.getenv(key, default)


def get_env_or_raise(key: str) -> str:
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"Environment variable {key} is not set")
    return value


class Config:
    LOG_LEVEL: str = get_env('LOG_LEVEL', 'INFO')

    # Server settings
    HOST: str = get_env('HOST', '0.0.0.0')
    PORT: int = int(get_env('PORT', '8080'))

    # RPC settings
    RPC_URL: Dict[str, str] = {}
    CACHE_TTL: Dict[str, int] = {}

    @classmethod
    def load_rpc_configs(cls):
        for key, value in os.environ.items():
            if key.startswith("RPC_"):
                chain = key[4:].lower()
                cls.RPC_URL[chain] = value
                cache_time_key = f"CACHE_TTL_{chain.upper()}"
                cls.CACHE_TTL[chain] = int(get_env_or_raise(cache_time_key))


config = Config()
config.load_rpc_configs()
