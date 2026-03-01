from redis import Redis
from rq import Queue

from shared.config import settings


def get_redis_connection() -> Redis:
    return Redis.from_url(settings.redis_url)


def get_queue(name: str) -> Queue:
    return Queue(name, connection=get_redis_connection())
