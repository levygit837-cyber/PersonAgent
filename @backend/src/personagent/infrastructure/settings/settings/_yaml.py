"""Carregamento de configuração via YAML."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values


class SettingsYamlMixin:
    """Mixin com métodos de carregamento YAML/env para Settings."""

    @classmethod
    def from_yaml(cls, path: str | Path):  # type: ignore[no-untyped-def]
        """Carrega configuração de um arquivo YAML, mesclando com variáveis de ambiente."""
        path = Path(path)
        yaml_data: dict[str, Any] = {}

        if path.exists():
            with open(path, encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}

        # Converte keys de env para lowercase para compatibilidade
        flattened: dict[str, Any] = {}
        for section, values in yaml_data.items():
            if isinstance(values, dict):
                for key, val in values.items():
                    flattened[f"{section}_{key}".lower()] = val

        process_env = cls._settings_values_from_env(os.environ)
        project_env = cls._settings_values_from_env(dotenv_values(path.parent / ".env"))

        # Mescla: defaults < YAML < ambiente herdado < .env do projeto.
        # O .env local fica por último para evitar que uma variável global/stale
        # como NVIDIA_API_KEY sobrescreva a credencial do projeto.
        merged = {**flattened, **process_env, **project_env}
        return cls(**merged, _env_file=None)

    @classmethod
    def _settings_values_from_env(cls, values: Mapping[str, Any]) -> dict[str, Any]:
        """Converte aliases de ambiente para nomes de campos do Settings."""
        alias_to_field = {
            str(field.alias): name for name, field in cls.model_fields.items() if field.alias
        }
        result: dict[str, Any] = {}
        for key, value in values.items():
            if value is None or value == "":
                continue
            field_name = alias_to_field.get(str(key))
            if field_name:
                result[field_name] = value
        return result
