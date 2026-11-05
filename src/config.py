"""Configuração lida do ambiente (12-factor).

A app não sobe se um valor estiver fora do formato esperado. Defaults do
`.env.example` estão replicados aqui para o processo rodar sem `.env`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    brasilapi_base_url: str = "https://brasilapi.com.br/api"
    minhareceita_base_url: str = "https://minhareceita.org"
    cache_ttl_horas: int = Field(default=24, gt=0)
    http_timeout_segundos: int = Field(default=8, gt=0)
    database_url: str = "sqlite:///./dados/consulta_cnpj.db"


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração (cacheada para a vida do processo)."""
    return Settings()
