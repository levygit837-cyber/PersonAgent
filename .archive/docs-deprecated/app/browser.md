# Browser no PersonAgent

## Visão geral

O agente pode navegar na web, ler documentação e interagir com páginas via duas runtimes: LightPanda (rápido, leve) e CDP/Chrome (fidelidade total).

## Runtimes

| Runtime | Características | Quando usar |
|---------|----------------|-------------|
| **LightPanda** | Headless, HTML mirror, element mapping, baixa memória | Leitura, scraping, busca |
| **CDP/Chrome** | Pixel-perfect, JavaScript completo, DevTools | Apps complexos, testes visuais |

## LightPandaBrowserWorker

- Gerencia sessões por conversa, caches de renderização, stylesheets e console logs.
- Auto-inicia container se configurado (`auto_start_lightpanda=True`).
- Warmup é best-effort; falhas são logadas mas não impedem o chat.

## Ferramentas de Browser

| Ferramenta | Função |
|------------|--------|
| `BrowserOpen` | Abre URL |
| `BrowserSearch` | Busca na web |
| `BrowserExtractContent` | Extrai texto da página |
| `BrowserClick`, `BrowserType` | Interação com elementos |
| `BrowserScreenshot` | Captura de tela |
| `BrowserScript` | Executa JS ou CDP allowlisted |

## Workspace V2 (Persistência)

- Tabs, anotações e timeline são persistidos em PostgreSQL.
- HTML snapshots grandes permanecem transientes.
- Migração automática de metadados legados.

## Annotations

- Ancoradas a node IDs do DOM.
- Incluem seletor, frame, shadow path.
- Criadas via API e visíveis na timeline.

## Referências

- ADR 0013: Browser Workspace V2
