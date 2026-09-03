"""Environment-driven configuration for every agent.

All settings load from the process environment (and an optional ``.env``
file) under the ``BACKEND_AGENTIC__`` prefix, with ``__`` as the nested
delimiter, e.g.::

    BACKEND_AGENTIC__REST__BASE_URL=http://localhost:8000
    BACKEND_AGENTIC__DB__CONNECTIONS__ORDERS=postgresql+psycopg://postgres:postgres@localhost:5432/orders
    BACKEND_AGENTIC__KAFKA__BOOTSTRAP_SERVERS=localhost:19092

See ``.env.example`` for the full set.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RestSettings(BaseModel):
    base_url: str = "http://localhost:8000"
    timeout: float = 10.0
    verify_ssl: bool = True
    default_headers: dict[str, str] = Field(default_factory=dict)
    retry_attempts: int = 3


class GraphQLSettings(BaseModel):
    endpoint: str = "http://localhost:8000/graphql"
    timeout: float = 10.0
    default_headers: dict[str, str] = Field(default_factory=dict)


class DbSettings(BaseModel):
    # named connections, e.g. {"orders": "postgresql+psycopg://..."}
    connections: dict[str, str] = Field(default_factory=dict)
    default_connection: str = "default"


class KafkaSettings(BaseModel):
    bootstrap_servers: str = "localhost:19092"
    consumer_group_prefix: str = "backend-agentic"
    security_config: dict[str, str] = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BACKEND_AGENTIC__",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    rest: RestSettings = Field(default_factory=RestSettings)
    graphql: GraphQLSettings = Field(default_factory=GraphQLSettings)
    db: DbSettings = Field(default_factory=DbSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
