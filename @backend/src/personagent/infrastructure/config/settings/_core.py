"""Helpers e singleton para Settings."""

from pathlib import Path
from typing import Any


def get_project_root() -> Path:
    """Retorna o diretório raiz do projeto (onde está config.yaml)."""
    return Path(__file__).parent.parent.parent.parent.parent.parent.parent


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


# Singleton global
_settings: Any = None


def get_settings() -> Any:
    """Retorna a instância singleton de Settings."""
    global _settings
    if _settings is None:
        # Tenta carregar de config.yaml primeiro, senão usa .env
        config_path = get_project_root() / "config.yaml"
        # Import local para evitar ciclo na primeira importação
        from . import Settings

        _settings = Settings.from_yaml(config_path) if config_path.exists() else Settings()
    return _settings


def reset_settings() -> None:
    """Reseta o singleton (útil para testes)."""
    global _settings
    _settings = None
