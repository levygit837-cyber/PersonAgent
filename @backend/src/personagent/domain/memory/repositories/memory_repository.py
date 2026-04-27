"""Interface do repositório de memória.

Define contratos para scan, leitura, escrita e remoção de arquivos
de memória no filesystem. Implementações concretas ficam na camada
de infraestrutura.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from personagent.domain.memory.models.memory_file import MemoryFile, MemoryHeader, MemoryIndex
from personagent.domain.memory.models.memory_types import MemoryScope, MemoryType


class MemoryRepository(ABC):
    """Repositório de memória de longo prazo.

    Responsável por operações de I/O no filesystem onde as memórias
    são armazenadas como arquivos Markdown com frontmatter YAML.
    """

    @abstractmethod
    async def scan(
        self,
        memory_dir: Path,
        max_files: int = 200,
    ) -> list[MemoryHeader]:
        """Escaneia um diretório de memória e retorna metadados de todos os .md.

        Args:
            memory_dir: Diretório raiz da memória.
            max_files: Número máximo de arquivos a retornar.

        Returns:
            Lista de headers ordenados por mtime (mais recente primeiro).
        """
        ...

    @abstractmethod
    async def read(
        self,
        file_path: Path,
        max_lines: int = 200,
        max_bytes: int = 25_000,
    ) -> MemoryFile | None:
        """Lê um arquivo de memória do disco.

        Args:
            file_path: Path absoluto do arquivo.
            max_lines: Máximo de linhas do corpo (após frontmatter).
            max_bytes: Máximo de bytes do conteúdo total.

        Returns:
            MemoryFile parseado ou None se o arquivo não existir/inválido.
        """
        ...

    @abstractmethod
    async def write(
        self,
        memory_file: MemoryFile,
    ) -> Path:
        """Escreve um arquivo de memória no disco.

        Cria diretórios intermediários se necessário.

        Args:
            memory_file: Dados da memória a persistir.

        Returns:
            Path do arquivo escrito.
        """
        ...

    @abstractmethod
    async def delete(self, file_path: Path) -> bool:
        """Remove um arquivo de memória.

        Args:
            file_path: Path absoluto do arquivo.

        Returns:
            True se o arquivo foi removido, False se não existia.
        """
        ...

    @abstractmethod
    async def read_index(self, memory_dir: Path) -> MemoryIndex | None:
        """Lê o arquivo MEMORY.md de um diretório de memória.

        Args:
            memory_dir: Diretório que contém o MEMORY.md.

        Returns:
            MemoryIndex ou None se o arquivo não existir.
        """
        ...

    @abstractmethod
    async def update_index(
        self,
        memory_dir: Path,
        entries: list[dict[str, Any]],
        max_lines: int = 200,
        max_bytes: int = 25_000,
    ) -> Path:
        """Atualiza o arquivo MEMORY.md com uma lista de entradas.

        Args:
            memory_dir: Diretório da memória.
            entries: Lista de dicts com name, description, type.
            max_lines: Limite de linhas do índice.
            max_bytes: Limite de bytes do índice.

        Returns:
            Path do MEMORY.md atualizado.
        """
        ...

    @abstractmethod
    async def get_memory_dir(
        self,
        project_slug: str,
        scope: MemoryScope = MemoryScope.PRIVATE,
        agent_type: str | None = None,
    ) -> Path:
        """Retorna o diretório de memória para um projeto/escopo.

        Args:
            project_slug: Identificador do projeto/workspace.
            scope: Escopo de persistência.
            agent_type: Tipo do agente (para agent-memory).

        Returns:
            Path do diretório de memória.
        """
        ...

    @abstractmethod
    async def list_by_type(
        self,
        memory_dir: Path,
        memory_type: MemoryType,
        max_files: int = 200,
    ) -> list[MemoryHeader]:
        """Lista memórias filtradas por tipo.

        Args:
            memory_dir: Diretório raiz da memória.
            memory_type: Tipo de memória a filtrar.
            max_files: Número máximo de resultados.

        Returns:
            Lista de headers do tipo especificado.
        """
        ...
