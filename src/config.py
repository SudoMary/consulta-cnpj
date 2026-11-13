"""Configuração lida do ambiente (12-factor).

A app não sobe se um valor estiver fora do formato esperado. Defaults do
`.env.example` estão replicados aqui para o processo rodar sem `.env`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
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

    # Assistente: sem chave, ele fica desligado e o resto funciona igual.
    # SecretStr mascara a chave em log e mensagem de erro.
    anthropic_api_key: SecretStr | None = None
    assistente_modelo: str = "claude-opus-5-5"
    # Cada pergunta custa dinheiro e o site não tem login: o limite protege a conta.
    assistente_limite_diario: int = Field(default=20, gt=0)

    @property
    def url_banco(self) -> str:
        """URL do banco no formato do SQLAlchemy, com o driver instalado.

        O Supabase entrega ``postgresql://...``; sem o ``+psycopg``, o
        SQLAlchemy procuraria o driver antigo (psycopg2), que não está
        instalado. SQLite passa sem mudança.
        """
        for prefixo in ("postgresql://", "postgres://"):
            if self.database_url.startswith(prefixo):
                return "postgresql+psycopg://" + self.database_url.removeprefix(prefixo)
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração (cacheada para a vida do processo)."""
    return Settings()
