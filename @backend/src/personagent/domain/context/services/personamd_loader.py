"""persona.md loader service.

Este serviço descobre e carrega arquivos persona.md do sistema de arquivos,
seguindo a prioridade: managed → user → project → local.
Suporta a diretiva @include para incluir outros arquivos.
"""

from __future__ import annotations

import re
from pathlib import Path

from personagent.domain.context.models import MemoryFile


class PersonaMdLoader:
    """Carrega arquivos persona.md com suporte a @include.

    A ordem de prioridade é:
    1. Managed memory (/etc/claude-code/persona.md ou CLAUDE.md)
    2. User memory (~/.claude/persona.md ou CLAUDE.md)
    3. Project memory (persona.md/CLAUDE.md, .claude/*.md, .claude/rules/*.md)
    4. Local memory (persona.local.md ou CLAUDE.local.md)
    """

    # Extensões de arquivo permitidas para @include
    _TEXT_EXTENSIONS = {
        ".md",
        ".txt",
        ".text",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".csv",
        ".py",
        ".js",
        ".ts",
        ".dart",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
    }

    # Regex para detectar @include directives
    _INCLUDE_PATTERN = re.compile(r"@(\S+)")

    def __init__(
        self,
        workspace_root: str | Path,
        enable_persona_md: bool = True,
        additional_directories: list[str | Path] | None = None,
    ) -> None:
        """Inicializa o loader.

        Args:
            workspace_root: Diretório raiz do workspace.
            enable_persona_md: Se False, desabilita carregamento de persona.md.
            additional_directories: Diretórios adicionais para buscar persona.md.
        """
        self._workspace_root = Path(workspace_root).expanduser().resolve()
        self._enable_persona_md = enable_persona_md
        self._additional_directories = [
            Path(d).expanduser().resolve() for d in (additional_directories or [])
        ]
        self._loaded_paths: set[Path] = set()  # Para prevenir loops

    def load_memory_files(self) -> list[MemoryFile]:
        """Carrega todos os arquivos de memória em ordem de prioridade.

        Returns:
            Lista de MemoryFile ordenada por prioridade (menor = mais antigo).
        """
        if not self._enable_persona_md:
            return []

        memory_files: list[MemoryFile] = []
        self._loaded_paths.clear()

        # Priority 1: Managed memory
        managed_file = self._load_managed_memory()
        if managed_file:
            memory_files.append(managed_file)

        # Priority 2: User memory
        user_file = self._load_user_memory()
        if user_file:
            memory_files.append(user_file)

        # Priority 3: Project memory
        project_files = self._load_project_memory()
        memory_files.extend(project_files)

        # Priority 4: Local memory
        local_file = self._load_local_memory()
        if local_file:
            memory_files.append(local_file)

        # Process @include directives
        memory_files = self._process_includes(memory_files)

        return memory_files

    def get_combined_content(self) -> str:
        """Retorna o conteúdo combinado de todos os arquivos persona.md.

        Returns:
            String com o conteúdo concatenado de todos os arquivos.
        """
        memory_files = self.load_memory_files()
        if not memory_files:
            return ""

        # Ordena por prioridade (menor = carregado primeiro)
        sorted_files = sorted(memory_files, key=lambda f: f.priority)

        contents = []
        for file in sorted_files:
            if file.content.strip():
                contents.append(f"# {file.path}\n\n{file.content}")

        return "\n\n---\n\n".join(contents)

    def _load_managed_memory(self) -> MemoryFile | None:
        """Carrega managed memory."""
        for path in (
            Path("/etc/claude-code/persona.md"),
            Path("/etc/claude-code/CLAUDE.md"),
        ):
            if not path.exists():
                continue
            content = self._read_file_safely(path)
            if content:
                return MemoryFile.create(path, content, priority=1)
        return None

    def _load_user_memory(self) -> MemoryFile | None:
        """Carrega user memory."""
        for path in (
            Path.home() / ".claude" / "persona.md",
            Path.home() / ".claude" / "CLAUDE.md",
        ):
            if not path.exists():
                continue
            content = self._read_file_safely(path)
            if content:
                return MemoryFile.create(path, content, priority=2)
        return None

    def _load_project_memory(self) -> list[MemoryFile]:
        """Carrega project memory do workspace e diretórios adicionais."""
        files: list[MemoryFile] = []
        search_roots = [self._workspace_root] + self._additional_directories

        for root in search_roots:
            if not root.exists() or not root.is_dir():
                continue

            for memory_path in (
                root / "persona.md",
                root / "CLAUDE.md",
                root / ".claude" / "persona.md",
                root / ".claude" / "CLAUDE.md",
            ):
                if memory_path.exists():
                    content = self._read_file_safely(memory_path)
                    if content:
                        files.append(MemoryFile.create(memory_path, content, priority=3))

            # .claude/rules/*.md
            rules_dir = root / ".claude" / "rules"
            if rules_dir.exists() and rules_dir.is_dir():
                for rule_file in sorted(rules_dir.glob("*.md")):
                    content = self._read_file_safely(rule_file)
                    if content:
                        files.append(MemoryFile.create(rule_file, content, priority=3))

        return files

    def _load_local_memory(self) -> MemoryFile | None:
        """Carrega local memory."""
        for path in (
            self._workspace_root / "persona.local.md",
            self._workspace_root / "CLAUDE.local.md",
        ):
            if not path.exists():
                continue
            content = self._read_file_safely(path)
            if content:
                return MemoryFile.create(path, content, priority=4)
        return None

    def _process_includes(self, files: list[MemoryFile]) -> list[MemoryFile]:
        """Processa diretivas @include nos arquivos.

        Args:
            files: Lista de MemoryFile originais.

        Returns:
            Lista expandida com arquivos incluídos.
        """
        result: list[MemoryFile] = []
        processed_files: set[Path] = set()

        for file in files:
            # Adiciona o arquivo original se ainda não foi processado
            if file.path not in processed_files:
                result.append(file)
                processed_files.add(file.path)

            # Busca @include directives
            included_files = self._extract_includes(file)
            for included in included_files:
                if included.path not in processed_files:
                    result.append(included)
                    processed_files.add(included.path)

        return result

    def _extract_includes(self, file: MemoryFile) -> list[MemoryFile]:
        """Extrai e carrega arquivos incluído via @include.

        Args:
            file: MemoryFile com conteúdo para processar.

        Returns:
            Lista de MemoryFile incluídos.
        """
        included: list[MemoryFile] = []
        matches = self._INCLUDE_PATTERN.findall(file.content)

        for match in matches:
            include_path = self._resolve_include_path(match, file.path)
            if include_path and include_path.exists():
                # Prevenir loops
                if include_path in self._loaded_paths:
                    continue
                self._loaded_paths.add(include_path)

                content = self._read_file_safely(include_path)
                if content:
                    included.append(
                        MemoryFile.create(
                            include_path,
                            content,
                            priority=file.priority,
                            is_injected=True,
                        )
                    )

        return included

    def _resolve_include_path(self, include_spec: str, base_path: Path) -> Path | None:
        """Resolve um caminho de @include.

        Suporta:
        - @path (relativo ao diretório do arquivo atual)
        - @./path (relativo ao diretório do arquivo atual)
        - @~/path (relativo ao home do usuário)
        - @/absolute/path (caminho absoluto)

        Args:
            include_spec: Especificação do caminho após @.
            base_path: Caminho do arquivo que contém o @include.

        Returns:
            Path resolvido ou None se inválido.
        """
        if not include_spec:
            return None

        # @~/path
        if include_spec.startswith("~/"):
            return Path.home() / include_spec[2:]

        # @/absolute/path
        if include_spec.startswith("/"):
            return Path(include_spec)

        # @./path ou @path (relativo)
        relative = include_spec[2:] if include_spec.startswith("./") else include_spec

        # Relativo ao diretório do arquivo atual
        base_dir = base_path.parent
        resolved = base_dir / relative

        try:
            return resolved.resolve()
        except (OSError, RuntimeError):
            return None

    def _read_file_safely(self, path: Path) -> str | None:
        """Lê um arquivo de forma segura.

        Args:
            path: Caminho do arquivo.

        Returns:
            Conteúdo do arquivo ou None se falhar.
        """
        try:
            # Verificar se é arquivo de texto permitido
            if path.suffix.lower() not in self._TEXT_EXTENSIONS:
                return None

            content = path.read_text(encoding="utf-8", errors="replace")
            # Limitar tamanho para evitar problemas
            max_chars = 50_000
            if len(content) > max_chars:
                content = content[:max_chars] + "\n\n[...truncated...]"
            return content
        except (OSError, UnicodeDecodeError):
            return None
