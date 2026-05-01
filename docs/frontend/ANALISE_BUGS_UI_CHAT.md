# Análise de Bugs da UI de Chat — Relatório Técnico

**Data:** 2026-04-30  
**Escopo:** `@desktop-electron/src/` (React + Zustand + Tailwind) + `@backend/src/` (FastAPI/SSE)  
**Método:** Análise estática de código + rastreamento de fluxo de dados

---

## Problema 1: Todo Dock piscando/desaparecendo durante tool calls

### Causa Raiz
**Local:** `@desktop-electron/src/components/chat/input-dock.tsx` — `InputTodoDock` (linhas 613–671) + `latestTodoSnapshot` (linhas 769–787)

O componente `InputTodoDock` declara:

```tsx
const liveSnapshot = useMemo(() => latestTodoSnapshot(messages, activeAgentId), [messages, activeAgentId]);
```

Durante streaming, o array `messages` é atualizado a cada **50 ms** pelo mecanismo de text flush buffer (`chat-store.ts:1398–1416`). A função `latestTodoSnapshot` **cria um novo objeto a cada chamada**, mesmo que o conteúdo dos todos não tenha mudado.

O `useEffect` na linha 623–628 dispara sempre que `liveSnapshot` muda de referência:

```tsx
useEffect(() => {
  if (isExecuting && liveSnapshot) {
    setDisplaySnapshot(liveSnapshot);
    setExiting(false);        // ← Cancela qualquer animação de saída
  }
}, [isExecuting, liveSnapshot]);
```

Isso força um **re-set do estado do componente** a cada ~50 ms, re-disparando a animação CSS `personagent-todo-rise` e resetando o estado `exiting`. O resultado visual é o painel de Todo "piscando" ou desaparecendo e reaparecendo constantemente durante execução de tools ou streaming.

### Correção Recomendada
1. **Estabilizar a referência do snapshot** comparando pelo `key` gerado dentro de `latestTodoSnapshot` (que já é determinístico: `block.id + todos[].id + status + content`).
2. **Mudar a dependência do `useEffect`** de `liveSnapshot` (objeto) para o `key` do snapshot (string), evitando re-disparo desnecessário.
3. Alternativamente, **bufferar mudanças do Todo Dock** com debounce (ex: só atualizar o `displaySnapshot` se o `key` permanecer estável por 150–200 ms).

### Plano de Implementação
1. Refatorar `latestTodoSnapshot` para retornar um tuple `[key, snapshot]` ou expor o `key` separadamente.
2. No `InputTodoDock`, adicionar `const liveKey = liveSnapshot?.key;` e usar `liveKey` como dependência do `useEffect` em vez de `liveSnapshot`.
3. Garantir que `setDisplaySnapshot` só seja chamado quando `liveKey !== displaySnapshot?.key`.

---

## Problema 2: Botão "Stop" some temporariamente

### Causa Raiz
**Locais:** `@desktop-electron/src/stores/chat-store.ts` — `flushTextBuffer` (linhas 1419–1443) + `handleChunk` (linhas 1170–1315)

O estado `isStreaming` controla o botão Stop/Send. Ele é setado para `true` apenas no **início** de `sendMessage` (linha 292) e em `approvePendingTool` (linha 449). No entanto, ele é setado para `false` em múltiplos momentos:

- `conversation_saved` → `false` (linha 1248)
- `permission_required` → `false` (linha 1286)
- `plan_approval_requested` → `false` (linha 1218)
- `flushTextBuffer` quando `finish_reason` não é `"tool_calls"` → `false` (linha 1435)
- `finally` do `sendMessage` quando o stream SSE termina → `false` (linha 336)

**O bug crítico está em `flushTextBuffer:1435`:**

```tsx
const isFinalFinish = Boolean(finishReason && finishReason !== "tool_calls");
set((state) => ({
  isStreaming: isFinalFinish && state.activeAgentId === agentId ? false : state.isStreaming,
  ...
}));
```

O backend mantém a conexão SSE aberta durante **múltiplos turns** (LLM → tools → LLM). Quando o modelo termina um turn com `finish_reason="stop"`, esse código seta `isStreaming = false`. O backend então executa tools e reinicia o LLM no **mesmo stream SSE**. Quando os novos chunks de content/reasoning chegam ao frontend via `handleChunk` → `queueTextChunk`, **nenhum código seta `isStreaming = true` novamente**.

Resultado: entre o fim de um turn e o início do próximo (dentro do mesmo stream), o botão vira Send (`isStreaming = false`). Depois de alguns segundos, quando o usuário vê que ainda há atividade, o botão não volta sozinho — ele só volta se uma nova chamada explícita (`sendMessage`, `approvePendingTool`) for feita, ou se o usuário interagir.

### Correção Recomendada
1. **Re-hidratar `isStreaming` no `handleChunk`**: no início de `handleChunk`, se `state.isStreaming === false` mas `state.activeAgentId === agentId` e o chunk contém conteúdo/reasoning (não é apenas um evento de término), setar `isStreaming = true`.
2. **Alternativa (mais robusta)**: garantir que qualquer chunk recebido dentro de um stream ativo force `isStreaming = true`, exceto chunks explicitamente finais (`conversation_saved`, `error`, etc.).

### Plano de Implementação
1. Adicionar no topo de `handleChunk` (antes do dispatch de eventos):
   ```tsx
   if (!get().isStreaming && get().activeAgentId === agentId && chunk.content) {
     set({ isStreaming: true });
   }
   ```
   (com cuidado para não reativar em eventos pós-término).
2. Revisar todos os pontos onde `isStreaming` é setado para `false` para garantir que só ocorram quando o stream SSE realmente terminou ou foi interrompido por ação do usuário.

---

## Problema 3: Shell com falso positivo (vermelho antes da aprovação)

### Causa Raiz
**Local:** `@desktop-electron/src/components/chat/tool-block.tsx` — `isErrorStatus` (linhas 882–884)

```tsx
function isErrorStatus(status: ToolBlockStatus) {
  return status === "error" || status === "permission_required";
}
```

Quando o backend emite um evento `permission_required` para um comando shell, o frontend renderiza o bloco com a mesma cor de erro (`text-destructive`, `bg-destructive`). Visualmente, o comando parece ter **falhado** quando na verdade está apenas **aguardando aprovação** do usuário.

Isso afeta:
- O **dot de status** (`StatusDot`, linha 479) — usa `bg-destructive`
- O **texto do comando** (`ShellToolEvent`, linha 279) — usa `text-destructive`
- O **grupo compacto** (`CompactToolGroupBlock`, linha 48) — detecta `hasError`

### Correção Recomendada
1. **Separar visualmente** `permission_required` de `error`. Criar um estado visual distinto (ex: amarelo/laranja `text-warning` / `bg-warning`).
2. Atualizar `StatusDot` para renderizar uma cor diferente quando `status === "permission_required"`.
3. Atualizar `shellCommandText`/`ShellToolEvent` para não aplicar `text-destructive` em `permission_required`.

### Plano de Implementação
1. Criar função `isWarningStatus(status)` ou tratar `permission_required` como caso separado.
2. Atualizar `StatusDot` para suportar `status="permission_required"` com cor de warning.
3. Atualizar `ShellToolEvent` para usar classe de warning em vez de destructiva.
4. Atualizar `CompactToolGroupBlock` para não contar `permission_required` como erro no cálculo de `hasError`.

---

## Problema 4: Dados incorretos no Painel (Tokens / Tool Calls)

### Causas Raiz (múltiplas)

#### 4A — Dupla contagem após `conversation_saved` (CRÍTICO)
**Local:** `@desktop-electron/src/stores/chat-store.ts` — `conversation_saved` handler (linha 1254)

```tsx
liveSessionUsage: state.activeAgentId ? state.liveSessionUsage : emptySessionUsage(),
```

No momento em que `conversation_saved` é processado, `state.activeAgentId` **ainda é truthy** (ele só é limpo na mesma chamada `set`, mas `state` refere-se ao estado anterior). Portanto, `liveSessionUsage` **nunca é resetado**.

Consequência: `SessionPanel.tsx` chama `mergeUsage(snapshot, liveUsage)`, somando os valores **reais** do backend com os valores **estimados** retidos no `liveSessionUsage`. Resultado: contadores dobrados ou mais.

**Correção:**
```tsx
liveSessionUsage: emptySessionUsage(),
```
(ou condicionar ao `agentId` correto, não ao `activeAgentId` do estado anterior).

#### 4B — Context tokens inflado com `total_tokens` (MÉDIO)
**Local:** `@backend/src/personagent/application/services/session_panel.py` — `_add_token_usage` (linhas 454–464)

```python
context_tokens = _first_int(
    raw_usage,
    (
        "total_tokens",        # ← inclui output tokens!
        "totalTokenCount",     # ← inclui output tokens!
        "prompt_tokens",       # correto
        "input_tokens",        # correto
        "promptTokenCount",    # correto
    ),
)
```

`total_tokens` = input + output. Usar isso como `context_tokens` infla o valor.

**Correção:** Remover `"total_tokens"` e `"totalTokenCount"` do fallback, ou movê-los para **depois** dos campos específicos de input.

#### 4C — Context tokens sempre marcado como `estimated` (LEVE)
**Local:** `@backend/src/personagent/application/services/session_panel.py` (linha 470)

```python
usage["context_tokens"]["estimated"] = True   # ← incondicional
```

Mesmo quando o valor vem de `prompt_tokens` exato do provider, é marcado como estimado.

**Correção:** Marcar como `estimated` apenas quando o valor for de fato estimado (fallback para `len/4` ou similar).

### Plano de Implementação
1. **Frontend (`chat-store.ts`)**: Na linha 1254, trocar `state.activeAgentId ? state.liveSessionUsage : emptySessionUsage()` para `emptySessionUsage()` incondicionalmente no evento `conversation_saved`.
2. **Backend (`session_panel.py`)**: Reordenar/remover fallbacks de `context_tokens`; adicionar lógica condicional para `estimated`.
3. Adicionar testes unitários cobrindo `mergeUsage` com snapshot + liveUsage para garantir que não ocorra dupla contagem.

---

## Problema 5: Tab selecionando elementos aleatoriamente

### Causa Raiz
O navegador nativamente navega por todos os elementos focáveis (`tabIndex={0}`, `<button>`, `<a>`, `<input>`, etc.) quando o usuário pressiona Tab. No projeto, existem elementos intencionalmente focáveis que, uma vez focados, podem ser acionados com Enter/Space, causando ações indesejadas:

**Elementos com `tabIndex={0}` identificados:**
1. **Resize handle do painel lateral** (`chat-workspace.tsx:491`) — `role="separator"`, focável via Tab
2. **Close button de browser tabs** (`session-panel.tsx:1426`) — `role="button"`, focável via Tab, acionável com Enter/Space
3. **Browser viewport** (`session-panel.tsx:2301`) — `role="application"`, focável via Tab, intercepta `onKeyDown`

Além disso, **todos os `<button>` nativos** (botões de aprovação de tool, ações de mensagem, toggles) são focáveis por padrão. Quando o usuário pressiona Tab repetidamente, o foco salta entre esses elementos. Se pressionar Enter enquanto um botão sensível (ex: "Allow" de shell) está focado, o comando é confirmado acidentalmente.

### Correção Recomendada
A solução não é desabilitar o Tab completamente (isso quebraria acessibilidade), mas **controlar o focus ring** e **desabilitar foco em elementos não-essenciais ou perigosos**:

1. **Resize handle**: trocar `tabIndex={0}` para `tabIndex={-1}` (só focável programaticamente, não via Tab). O redimensionamento já funciona com mouse/touch.
2. **Browser viewport**: trocar `tabIndex={0}` para `tabIndex={-1}`. O viewport deve receber foco programático quando ativado, não via Tab da página.
3. **Botões sensíveis** (Allow/Reject de tool approval): adicionar `tabIndex={-1}` para evitar confirmação acidental via Tab + Enter.
4. **Implementar Focus Trap** opcional nos painéis modais (ex: aprovação de plano), restringindo Tab aos elementos do modal.

### Plano de Implementação
1. Remover `tabIndex={0}` dos elementos não-interativos (resize handle, browser viewport).
2. Avaliar cada botão crítico e aplicar `tabIndex={-1}` onde o risco de acionamento acidental for alto.
3. Considerar adicionar `focus-visible` styles claros para elementos que permanecem focáveis, dando feedback visual ao usuário.

---

## Problema 6: Toggle de Reasoning não persiste durante streaming

### Causa Raiz
**Local:** `@desktop-electron/src/components/chat/reasoning-block.tsx` (linhas 9–92)

O componente `ReasoningBlock` mantém o estado `expanded` como **estado local** (`useState`):

```tsx
const [expanded, setExpanded] = useState(isStreaming || !autoCollapse);
```

Quando o usuário clica em "Hide", `setExpanded(false)` é chamado. No entanto:

1. **Efeito de streaming força re-abertura** (linhas 34–37):
   ```tsx
   useEffect(() => {
     if (!isStreaming) return;
     setExpanded(true);   // ← Sempre reabre durante streaming
   }, [isStreaming]);
   ```
   Se `isStreaming` alternar entre `true` e `false` (ex: entre turns, ou ao receber `finish_reason`), o efeito reabre o reasoning.

2. **Novos blocos resetam o estado** (linhas 2820–2822 de `chat-store.ts`):
   ```tsx
   blocks.push({ id, content: chunk, isStreaming: true });
   parts.push({ kind: "reasoning", id: `part-${id}`, reasoningBlockId: id });
   ```
   Sempre que o fluxo de reasoning é interrompido e retomado, `appendReasoningChunk` cria um **novo** `reasoningBlock` com novo `id`. O React monta um novo componente `ReasoningBlock` com `useState` resetado para `expanded = true`.

3. **AgentMessage usa `memo`**, mas quando `message.parts` muda (novos blocos inseridos), a re-renderização ocorre, instanciando novos `ReasoningBlock`s.

Resultado: o usuário clica em "Hide", mas o próximo chunk de reasoning (ou novo bloco) aparece expandido novamente.

### Correção Recomendada
Mover o controle de visibilidade do reasoning de **estado local do componente** para **estado da mensagem ou store global**:

1. **Opção A (preferida)**: Adicionar `userExpanded: boolean | undefined` em cada `reasoningBlock` no `ChatMessageUi`. Quando o usuário clica em Hide/Show, atualizar essa propriedade no store. O `ReasoningBlock` lê `userExpanded` em vez de manter estado local.
2. **Opção B**: Adicionar uma flag global no `chat-store` (`reasoningGloballyHidden: boolean`). Quando o usuário clica em Hide, setar a flag. Todos os `ReasoningBlock`s respeitam a flag durante streaming.

### Plano de Implementação
1. Estender o tipo `ReasoningBlockUi` (em `types/chat.ts`) com campo opcional `userExpanded?: boolean`.
2. Adicionar ação `setReasoningBlockExpanded(messageId, blockId, expanded)` no `chat-store.ts`.
3. No `ReasoningBlock`, remover `useState(expanded)` e ler `userExpanded` via prop. Se `userExpanded === undefined`, usar o comportamento padrão (`isStreaming || !autoCollapse`).
4. No `appendReasoningChunk`, quando um novo bloco é criado, propagar o `userExpanded` do bloco anterior (se houver) para manter a preferência do usuário.

---

## Resumo Executivo

| Problema | Severidade | Causa Principal | Arquivos Críticos |
|----------|-----------|-----------------|-------------------|
| **1 — Todo piscando** | Alta | `useMemo` + `useEffect` disparam a cada 50 ms por mudança de referência de `messages` | `input-dock.tsx:613–628`, `chat-store.ts:1398–1416` |
| **2 — Stop sumindo** | Alta | `isStreaming` vai para `false` em `finish_reason` e nunca volta a `true` em turns subsequentes do mesmo SSE | `chat-store.ts:1435`, `chat-store.ts:1170–1315` |
| **3 — Shell falso positivo** | Média | `permission_required` é tratado visualmente como `error` | `tool-block.tsx:882–884` |
| **4 — Painel incorreto** | Alta | `liveSessionUsage` nunca é resetado; fallback de `context_tokens` usa `total_tokens` | `chat-store.ts:1254`, `session_panel.py:454–470` |
| **5 — Tab selvagem** | Média | Elementos não-essenciais e críticos têm `tabIndex={0}` ou são botões nativos focáveis | `chat-workspace.tsx:491`, `session-panel.tsx:1426,2301` |
| **6 — Reasoning toggle** | Média | Estado local `expanded` é resetado a cada novo bloco e forçado por `useEffect` durante streaming | `reasoning-block.tsx:18–37`, `chat-store.ts:2800–2833` |
