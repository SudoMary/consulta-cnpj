"""Testes da configuração lida do ambiente."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings


def _settings_sem_env_file() -> Settings:
    """Constrói Settings sem ler `.env`, para isolar do ambiente do dev."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


class TestDefaults:
    def test_defaults_batem_com_env_example(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange: limpa qualquer variável que o CI/OS possa ter setado
        for var in (
            "BRASILAPI_BASE_URL",
            "MINHARECEITA_BASE_URL",
            "CACHE_TTL_HORAS",
            "HTTP_TIMEOUT_SEGUNDOS",
            "DATABASE_URL",
        ):
            monkeypatch.delenv(var, raising=False)

        # Act
        settings = _settings_sem_env_file()

        # Assert
        assert settings.brasilapi_base_url == "https://brasilapi.com.br/api"
        assert settings.minhareceita_base_url == "https://minhareceita.org"
        assert settings.cache_ttl_horas == 24
        assert settings.http_timeout_segundos == 8
        assert settings.database_url == "sqlite:///./dados/consulta_cnpj.db"

    def test_cache_ttl_default_e_int_nao_str(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CACHE_TTL_HORAS", raising=False)
        settings = _settings_sem_env_file()
        assert isinstance(settings.cache_ttl_horas, int)


class TestOverridePorAmbiente:
    def test_override_via_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange
        monkeypatch.setenv("BRASILAPI_BASE_URL", "https://espelho.local/api")
        monkeypatch.setenv("HTTP_TIMEOUT_SEGUNDOS", "15")

        # Act
        settings = _settings_sem_env_file()

        # Assert
        assert settings.brasilapi_base_url == "https://espelho.local/api"
        assert settings.http_timeout_segundos == 15

    def test_cache_ttl_string_numerica_vira_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CACHE_TTL_HORAS", "48")
        settings = _settings_sem_env_file()
        assert settings.cache_ttl_horas == 48
        assert isinstance(settings.cache_ttl_horas, int)


class TestCaminhoDoBanco:
    @pytest.mark.parametrize(
        ("url", "caminho"),
        [
            ("sqlite:///./dados/consulta_cnpj.db", "./dados/consulta_cnpj.db"),
            ("sqlite:////var/dados/consulta.db", "/var/dados/consulta.db"),
        ],
        ids=["relativo", "absoluto"],
    )
    def test_tira_o_prefixo_da_url(
        self, monkeypatch: pytest.MonkeyPatch, url: str, caminho: str
    ) -> None:
        # `sqlite3.connect` recebe caminho de arquivo, não URL
        monkeypatch.setenv("DATABASE_URL", url)

        assert _settings_sem_env_file().caminho_banco == caminho


class TestValidacao:
    def test_cache_ttl_nao_positivo_levanta_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CACHE_TTL_HORAS", "0")

        with pytest.raises(ValidationError):
            _settings_sem_env_file()
