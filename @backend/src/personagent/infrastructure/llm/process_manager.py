"""Gerenciador do processo llama-server (start/kill automático)."""

import asyncio
import os
import shutil
import signal
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

import structlog

from personagent.infrastructure.config.settings import get_project_root, get_settings

logger = structlog.get_logger(__name__)


class LlamaServerProcessManager:
    """
    Gerencia o ciclo de vida do processo llama-server.
    Inicia automaticamente se não estiver rodando e encerra na finalização.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen[Any] | None = None
        self._settings = get_settings()
        self._shutdown_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        """Verifica se o llama-server está rodando."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def find_binary(self) -> str | None:
        """Localiza o binário do llama-server."""
        # 1. Caminho configurado (resolvido relativo à raiz do projeto)
        if self._settings.llama_bin_path:
            raw_path = Path(self._settings.llama_bin_path).expanduser()
            if raw_path.is_absolute():
                path = raw_path.resolve()
            else:
                path = (get_project_root() / raw_path).resolve()
            if path.exists():
                return str(path)
            logger.warning("llama_bin_configured_not_found", path=str(path))

        # 2. Procura no PATH
        binary = shutil.which("llama-server")
        if binary:
            logger.warning("llama_bin_fallback_to_path", binary=binary)
            return binary

        # 3. Procura em locais comuns
        possible_paths = [
            Path.home()
            / "Projetos"
            / "PersonAgent"
            / "@llama"
            / "llama-cpp-turboquant"
            / "build"
            / "bin"
            / "llama-server",
            Path.home()
            / "PersonAgent"
            / "@llama"
            / "llama-cpp-turboquant"
            / "build"
            / "bin"
            / "llama-server",
            get_project_root()
            / "@llama"
            / "llama-cpp-turboquant"
            / "build"
            / "bin"
            / "llama-server",
        ]
        for p in possible_paths:
            if p.exists():
                return str(p)

        return None

    def find_model(self) -> str | None:
        """Localiza o arquivo GGUF do modelo."""
        model_path = Path(self._settings.llama_model_path).expanduser()

        if model_path.is_file():
            return str(model_path)

        if model_path.is_dir():
            gguf_files = [f for f in model_path.glob("*.gguf") if "mmproj" not in f.name.lower()]
            if gguf_files:
                return str(gguf_files[0])

        return None

    async def start(self) -> bool:
        """Inicia o llama-server se necessário."""
        if self.is_running:
            logger.info("llama_server_already_running", pid=self._process.pid)
            return True

        binary = self.find_binary()
        if not binary:
            logger.error("llama_server_binary_not_found")
            return False

        model = self.find_model()
        if not model:
            logger.error("llama_model_not_found", path=self._settings.llama_model_path)
            return False

        cmd = [
            binary,
            "-m",
            model,
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--ctx-size",
            str(self._settings.llama_ctx_size),
            "--n-gpu-layers",
            str(self._settings.llama_n_gpu_layers),
            "--threads",
            str(self._settings.llama_threads),
            "--temp",
            str(self._settings.llama_temperature),
            "--cache-type-k",
            self._settings.llama_cache_type_k,
            "--cache-type-v",
            self._settings.llama_cache_type_v,
            "--reasoning",
            self._settings.llama_reasoning,
            "--reasoning-budget",
            str(self._settings.llama_reasoning_budget),
            "--jinja",
            "--verbose",
        ]

        logger.info(
            "starting_llama_server",
            binary=binary,
            model=model,
            ctx_size=self._settings.llama_ctx_size,
            cache_k=self._settings.llama_cache_type_k,
            cache_v=self._settings.llama_cache_type_v,
            reasoning=self._settings.llama_reasoning,
            reasoning_budget=self._settings.llama_reasoning_budget,
        )

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                preexec_fn=os.setsid,  # Permite matar o grupo de processos
            )

            # Aguarda o servidor iniciar (com timeout)
            started = await self._wait_for_startup(timeout=60.0)
            if started:
                logger.info("llama_server_started", pid=self._process.pid)
                # Inicia task para logar stdout
                asyncio.create_task(self._log_output())
                return True
            else:
                if self.is_running:
                    logger.error("llama_server_startup_timeout")
                self.stop()
                return False

        except Exception as exc:
            logger.error("llama_server_start_failed", error=str(exc))
            return False

    async def _wait_for_startup(self, timeout: float = 60.0) -> bool:
        """Aguarda o servidor estar pronto aceitando conexões."""
        import httpx

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if not self.is_running:
                logger.error("llama_server_process_died_during_startup")
                return False
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self._settings.llama_server_url}/health",
                        timeout=2.0,
                    )
                    if response.status_code == 200:
                        return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return False

    async def _log_output(self) -> None:
        """Loga a saída do processo llama-server."""
        if not self._process or not self._process.stdout:
            return

        while self.is_running:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, self._process.stdout.readline
                )
                if line:
                    line = line.strip()
                    if line:
                        # Erros e warnings do llama-server são importantes para debug
                        lower = line.lower()
                        if (
                            "error" in lower
                            or "failed" in lower
                            or "fatal" in lower
                            or "warning" in lower
                        ):
                            logger.warning("llama_server_output", output=line)
                        else:
                            logger.debug("llama_server_output", output=line)
            except Exception:
                break

    def stop(self) -> None:
        """Encerra o processo llama-server."""
        if not self._process:
            return

        logger.info("stopping_llama_server", pid=self._process.pid)

        # Tenta terminar o grupo de processos
        with suppress(ProcessLookupError, OSError):
            os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)

        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)
        except Exception as exc:
            logger.warning("llama_server_stop_error", error=str(exc))
        finally:
            self._process = None
            self._shutdown_event.set()

    async def restart(self) -> bool:
        """Reinicia o llama-server."""
        self.stop()
        await asyncio.sleep(1)
        return await self.start()
