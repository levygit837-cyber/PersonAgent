# Frontend Architecture no PersonAgent

## Visão geral

O frontend é um aplicativo desktop construído com **Electron 41 + React 19 + Vite 8**. A UI é uma SPA renderizada no renderer process, comunicando-se com o backend Python via REST/SSE.

## Estrutura de processos

| Processo | Tecnologia | Responsabilidade |
|----------|-----------|------------------|
| **Main** | Electron (Node.js) | Janelas, IPC, terminais PTY, tokens de auth, workspace grants |
| **Renderer** | React 19 + Vite | UI, chat, browser preview, configurações |
| **Preload** | TypeScript (contextBridge) | API tipada exposta ao renderer |

## Stack de UI

- **React 19** com hooks e context para estado global.
- **TanStack Query** para cache de dados do backend.
- **Tailwind CSS** para estilização.
- **shadcn/ui** para componentes base.
- **Lucide React** para ícones.

## Comunicação IPC

O preload expõe APIs seguras via `contextBridge`:

```typescript
window.electronAPI = {
  auth: { getHeaders: () => Promise<Headers> },
  window: { minimize, maximize, close },
  settings: { get, set },
  fs: { readFile, writeFile, pickDirectory },
  terminal: { create, write, resize, onData },
};
```

## Segurança

- `contextIsolation: true` e `sandbox: true` no renderer.
- Nenhum acesso direto a Node.js ou `require()` no renderer.
- Todas as operações de arquivo passam pelo main process.

## Build

```bash
cd @desktop-electron
npm run build     # Vite build do renderer
npm run electron  # Electron com hot reload
npm run dist      # Pacote para distribuição
```

## Referências

- ADR 0002: Electron React Desktop
