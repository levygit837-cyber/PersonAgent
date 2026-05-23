# AI-Guide: Command Registry and Slash Commands


## Safety Boundary

Este arquivo orienta navegação e manutenção. Ele não autoriza bypass de testes, permissões, validações de segurança, secrets ou revisão humana.

## Propósito

Sistema de comandos slash (`/command`) que permite ao usuário invocar comportamentos predefinidos via Markdown files ou built-ins hardcoded. Integra-se ao prompt como "reminders" de contexto adicional.

---

## Entry Points

### `CommandRegistry.list_commands` @ `domain/prompts/commands.py:172`
```python
def list_commands(
    self,
    workspace_root: str | Path | None = None,
) -> list[PromptCommand]
```
- Descobre e carrega arquivos `.md` de comandos de múltiplas raízes
- Retorna lista ordenada por nome

### `CommandRegistry.resolve` @ `:181`
```python
def resolve(
    self,
    message: str,
    workspace_root: str | Path | None = None,
) -> SlashCommandResolution | None
```
- Parseia mensagem como `/command args`
- Busca comando pelo nome
- Retorna `SlashCommandResolution` com comando expandido

### `CommandService.resolve_builtin` @ `:249`
```python
def resolve_builtin(self, message: str) -> BuiltinCommandResolution | None
```
- Resolve comandos built-in (hardcoded) como `/plan`, `/memory`, `/skills`

### `CommandService.list_builtin_commands` @ `:246`
```python
def list_builtin_commands(self) -> list[BuiltinCommand]
```
- Retorna todos os built-ins ordenados

---

## Classes Principais

### `PromptCommand` @ `:18` (comando de arquivo Markdown)
```python
@dataclass(frozen=True, slots=True)
class PromptCommand:
    name: str                    # Nome do comando (ex: "review/code")
    body: str                    # Corpo Markdown
    path: Path                   # Arquivo fonte
    description: str = ""
    allowed_tools: tuple[str, ...] = ()
    model: str | None = None
    argument_hint: str | None = None
    disable_model_invocation: bool = False
    when_to_use: str | None = None
    context: str = "inline"
    effort: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```
- `slash_name` → `/{name}`
- `expand(raw_arguments)` → substitui `$ARGUMENTS`, `$1`, `$2`, e `$key=value`

### `BuiltinCommand` @ `:100` (comando hardcoded)
```python
@dataclass(frozen=True, slots=True)
class BuiltinCommand:
    name: str
    description: str
    argument_hint: str | None = None
    allowed_tools: tuple[str, ...] = ()
    model: str | None = None
    effort: str | None = None
    should_query: bool = True      # Se False, é ação de UI apenas
    ui_action: str | None = None   # Identificador da ação de UI
```
- `reminder(raw_arguments)` → gera texto de reminder para injetar no prompt

### `CommandRegistry` @ `:166`
- Carrega comandos de arquivo
- Raízes de busca (em ordem):
  1. `workspace_root/.personagent/commands/`
  2. `cwd/.personagent/commands/`
  3. `~/.personagent/commands/`
  4. `extra_roots` (construtor)

### `CommandService` @ `:227`
- União: `CommandRegistry` + built-ins
- `resolve_prompt_command()` — comandos de arquivo
- `resolve_builtin()` — comandos built-in

---

## Built-in Commands (`BUILTIN_COMMANDS` @ `:260`)

| Comando | allowed_tools | ui_action | should_query |
|---------|---------------|-----------|--------------|
| `/plan` | `EnterPlanMode`, `ExitPlanMode`, `TodoWrite` | — | True |
| `/memory` | — | — | True |
| `/mcp` | `ListMcpResourcesTool`, `ReadMcpResourceTool`, `McpAuth` | — | True |
| `/skills` | `Skill`, `ToolSearch` | `skills_workspace` | False |
| `/permissions` | `Config` | `permissions` | False |
| `/model` | — | `model_picker` | False |
| `/effort` | — | `reasoning_picker` | False |
| `/context` | `Read`, `Glob`, `Grep`, `LSP` | — | True |
| `/clear` | — | `clear_chat` | False |
| `/compact` | — | `compact_context` | True |
| `/diff` | `shell`, `Read`, `Grep` | — | True |
| `/files` | `Read`, `Glob`, `Grep`, `LSP` | — | True |
| `/branch` | `shell` | — | True |
| `/usage` | — | `usage_status` | False |
| `/status` | `shell`, `Config` | `local_status` | False |
| `/doctor` | `shell`, `Config`, `ToolSearch`, `ListMcpResourcesTool` | — | True |
| `/help` | — | `command_help` | False |

---

## Parsing de Slash Command

### `parse_slash_invocation` @ `:366`
```python
def parse_slash_invocation(message: str) -> tuple[str, str] | None
```
- Requer começar com `/`
- Nome: `[A-Za-z0-9][A-Za-z0-9_.:/-]*` (permite nested como `/review/code`)
- Retorna: `(name, raw_arguments)`

---

## Formato de Arquivo de Comando

Arquivos `.md` em `.personagent/commands/`:
```markdown
---
description: "Code review command"
allowed-tools: ["Read", "Grep", "LSP"]
model: "codex"
argument-hint: "[file or scope]"
---
# Code Review

Review the following code for bugs, security issues, and style violations.
Focus on: $ARGUMENTS
```

Frontmatter keys suportados: `description`, `allowed-tools`, `model`, `argument-hint`, `disable-model-invocation`, `when-to-use`, `context`, `effort`, `reasoning`

---

## Quando Modificar

### Adicionar novo comando built-in
1. Adicionar entrada em `BUILTIN_COMMANDS` @ `:260`
2. Definir `ui_action` se for ação de UI
3. Definir `should_query=False` se não deve ir ao LLM
4. Adicionar teste em `tests/unit/domain/prompts/test_commands.py`

### Adicionar novo comando de arquivo
- Criar `.personagent/commands/<nome>.md` com frontmatter válido
- Não requer mudança de código

### Mudar parsing de slash commands
- Modificar regex em `parse_slash_invocation()` @ `:366`

---

## Anti-patterns

- **Nunca** adicionar lógica de negócio em `CommandService` — ele apenas resolve e delega
- **Nunca** confundir `should_query=False` (ação local) com tool calls — ações UI são handled pelo Electron
- **Nunca** permitir comandos com `disable_model_invocation=True` sem verificar se é seguro

---

## Dependências

- `domain.prompts.frontmatter` — parser de frontmatter YAML
- Consumido por: `ChatCompletionUseCase` (via `PromptBuilder`)