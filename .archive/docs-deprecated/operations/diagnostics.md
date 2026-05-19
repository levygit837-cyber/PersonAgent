# Diagnostics no PersonAgent

## Visão geral

Comandos e verificações para diagnosticar problemas no backend, desktop e runtime local.

## Checklist rápido

### Backend

```bash
# Health check
curl http://localhost:8000/health

# Verificar conexão com Postgres
python -c "import asyncio; from personagent.infrastructure.persistence.database import init_db; asyncio.run(init_db())"

# Verificar llama-server
curl http://localhost:8080/health

# Verificar logs
journalctl -u personagent -f  # se usar systemd
tail -f ~/.cache/personagent/logs/backend.log
```

### Desktop

```bash
# Logs do Electron
# Linux: ~/.config/personagent/logs/
# macOS: ~/Library/Logs/personagent/
# Windows: %APPDATA%\personagent\logs\

# Verificar token de auth
cat ~/.cache/personagent/local_auth_token

# Testar IPC
cd @desktop-electron && npm run test:ipc
```

### Docker Compose

```bash
docker compose ps
docker compose logs -f postgres
docker compose logs -f backend
```

## Métricas úteis

| Métrica | Como obter |
|---------|-----------|
| Latência do LLM | Logs: `llm_response_duration_ms` |
| Uso de VRAM | `nvidia-smi` ou logs do llama-server |
| Conexões Postgres | `SELECT count(*) FROM pg_stat_activity;` |
| Cache hit do prompt | Metadata: `prompt_build_duration_ms` baixo |

## Modo debug

```bash
# Backend
LOG_LEVEL=debug uvicorn personagent.interfaces.api.main:app --reload

# Desktop
DEBUG=1 npm run electron
```

## Referências

- `docs/operations/README.md`
