# Prompt Engineering Patterns Analysis

## Data: Saturday, 2026-05-30
## Autor: Devin Analysis + User Requirements
## Status: Draft - Pending Review

---

## 1. Problem Statement

Os system prompts atuais do PersonAgent sao textos planos extensos sem estrutura organizada que maximize a atencao e compreensao do agente. A analise dos arquivos em `@backend/src/personagent/domain/prompts/` revela que:

- **Prompts sao prosa densos**: Paragrafos longos sem separacao visual clara
- **Falta hierarquia numerada**: Instrucoes criticas misturadas com diretrizes secundarias
- **Sem uso de MAIUSCULAS para enfatizar**: Regras restritivas nao se destacam visualmente
- **Ausencia de padroes contextuais**: Nao ha separacao clara entre "o que fazer" vs "o que NUNCA fazer"
- **Sem secionamento consistente**: Falta de `## Section` organizada

### Exemplo do Problema (atual):
```
"For repository tasks, first classify the requested investigation depth privately as light, standard, deep, or exhaustive based on the user's wording, risk, scope, and requested confidence. The classification changes investigation budget, required repository surfaces, validation, and stop condition."
```

### Exemplo Melhorado (proposto):
```markdown
## 1. INVESTIGATION DEPTH CLASSIFICATION

ALWAYS classify the requested investigation depth BEFORE acting.
NEVER skip this step.

**Classification Levels:**
1. **LIGHT** - Narrow, low-risk question in identified area
2. **STANDARD** - Default for feature explanation, debugging (DEFAULT)
3. **DEEP** - Ambiguous, cross-cutting, behavioral, risky
4. **EXHAUSTIVE** - ONLY when user explicitly requests audit-level

**WHEN to STOP:**
- When you can name inspected files/functions
- When unresolved uncertainty is stated
- NEVER stop with "Done." or "OK." after tool use

**WHAT NOT TO DO:**
- NEVER mix investigation depth levels
- NEVER skip tree shape inspection for STANDARD+
- DON'T produce transcript-style final answers
```

---

## 2. Padroes Requeridos pelo Usuario

### 2.1 Instrucoes Numeradas
```markdown
## 2. INSTRUCTION SEQUENCE

1. First, classify investigation depth
2. Then, inspect tree shape and manifests
3. Next, search symbols with Grep/Glob
4. Finally, read targeted files and synthesize
5. STOP only when evidenced answer is ready
```

### 2.2 Bullets para Listas
```markdown
## 3. TOOL SELECTION RULES

- Use `Read` BEFORE editing any file
- Use `Grep` BEFORE reading many files manually
- Use `Edit` with exact old_string match
- Use `Glob` to discover directory structure
- NEVER use `Write` to overwrite without reading first
```

### 2.3 Padroes Contextuais Organizados
```markdown
## 4. BEHAVIOR CONTRACT

**WHEN to ACT:**
- Request is clear and unambiguous
- Tool results provide sufficient evidence
- Safety boundaries are respected

**WHEN to ASK:**
- Missing choice CANNOT be discovered
- Decision changes the outcome
- Risk is high and user approval required

**WHAT NOT TO DO:**
- NEVER claim without tool evidence
- NEVER skip validation for destructive actions
- DON'T produce one-word responses after tool use
- AVOID transcript-style final answers
- NEVER hallucinate file paths or function names

**ALWAYS:**
- Ground claims in tool results
- Preserve unrelated user work
- Revise approach when evidence contradicts
- Use safest specific tool for the job
```

### 2.4 Separacao por Secoes
```markdown
## 5. RESPONSE FORMAT

### 5.1 Simple Answers
- No bullets needed
- One short paragraph

### 5.2 Medium Answers
- 2-3 short headings
- Up to 4 dash bullets

### 5.3 Complex Answers
- Lead with outcome FIRST
- Separate: context, evidence, uncertainty
- Use paragraph labels: `Resultado:`, `Evidencia:`, `Incerteza:`

### 5.4 Prohibited Patterns
- NEVER use decorative section titles
- NEVER use ranking/table layouts unless requested
- AVOID emoji markers
- DON'T open with process confirmations
```

### 2.5 Uso de MAIUSCULAS para Enfatizar
```markdown
## 6. CRITICAL RULES (ALL CAPS)

**MANDATORY:**
- ALWAYS produce substantive answer after tool use
- ALWAYS verify before destructive operations
- ALWAYS name specific files in final answer

**PROHIBITED:**
- NEVER respond with "Done.", "OK.", "Fixed."
- NEVER hallucinate file paths
- NEVER skip validation for risky actions

**REQUIRED FORMAT:**
- DO use short paragraphs (1-3 sentences)
- DO use dash bullets for scanability
- DO ground claims in evidence
```

---

## 3. Skills Encontrados

### 3.1 Prompt Engineering Skills

| Skill | Installs | Relevancia |
|-------|----------|------------|
| `sickn33/antigravity-awesome-skills@prompt-engineer` | 1.1K | Alta - Padroes de engenharia de prompt |
| `melodic-software/claude-code-plugins@system-prompt-engineering` | 152 | Alta - System prompt engineering especifico |
| `prulloac/agent-skills@system-prompt-validator` | 14 | Media - Validacao de system prompts |
| `404kidwiz/claude-supercode-skills@prompt-engineer` | 97 | Media - Prompt engineering para codigo |

### 3.2 Skills Recomendadas para Instalacao

**1. `prompt-engineer` (1.1K installs)**
```bash
npx skills add sickn33/antigravity-awesome-skills@prompt-engineer -g -y
```

**2. `system-prompt-engineering` (152 installs)**
```bash
npx skills add melodic-software/claude-code-plugins@system-prompt-engineering -g -y
```

**3. `system-prompt-validator` (14 installs)**
```bash
npx skills add prulloac/agent-skills@system-prompt-validator -g -y
```

---

## 4. Analise dos Prompts Atuais

### 4.1 Estrutura Atual

O sistema usa `SystemPromptSection` que retorna strings via funcoes. A estrutura modular e boa, mas o conteudo precisa de:

1. **Hierarquia visual** - usar `##`, `###`, `####`
2. **Enfase tipografica** - MAIUSCULAS para criticos
3. **Separacao semantica** - WHEN/DO vs WHEN NOT/NEVER
4. **Numeracao sequencial** - passos ordenados
5. **Bullets consistentes** - listas escaneaveis

### 4.2 Arquivos Impactados

- `@backend/src/personagent/domain/prompts/prompt.py` - Core system prompts
- `@backend/src/personagent/domain/prompts/sections/agent.py` - Agent sections
- `@backend/src/personagent/domain/prompts/sections/execution.py` - Execution sections
- `@backend/src/personagent/domain/prompts/sections/tool_prompts.py` - Tool prompts
- `@backend/src/personagent/domain/prompts/sections/states.py` - State sections

---

## 5. Proposta de Melhoria

### 5.1 Template de Section Reestruturado

```python
def example_section() -> str:
    return """## X. SECTION NAME

**PURPOSE:** One-line summary of what this section controls.

### X.1 INSTRUCTIONS (Numerated)

1. **FIRST ACTION:** Description of what to do
   - Sub-bullet with detail
   - Another detail

2. **SECOND ACTION:** Description
   - Use `ToolName` for this
   - Check `specific_condition` before proceeding

3. **FINAL ACTION:** Description
   - STOP condition
   - Validation requirement

### X.2 RULES (Bullets)

**WHEN to ACT:**
- Condition 1
- Condition 2

**WHEN to ASK:**
- Condition 3
- Condition 4

**WHAT NOT TO DO:**
- NEVER do X
- NEVER do Y
- DON'T do Z

**ALWAYS:**
- DO verify before destructive actions
- DO name specific files in answers
- DO ground claims in evidence

### X.3 FORMAT

- Use short paragraphs (1-3 sentences)
- Use `-` dash bullets (flat, no nesting)
- Use paragraph labels when helpful: `Resultado:`, `Evidencia:`
- NEVER use decorative markers
"""
```

### 5.2 Hierarquia de Enfase

```markdown
# CRITICAL RULES (H1 - Rarely used)
## Section Name (H2 - Main sections)
### Sub-section (H3 - Grouping)
#### Detail (H4 - Specific instruction)

**BOLD** - Important terms
*ITALIC* - Emphasis
`CODE` - Tool names, file paths

ALL CAPS - CRITICAL, MANDATORY, NEVER, ALWAYS, DO, DON'T
```

---

## 6. Proximos Passos

1. [ ] Instalar skills de prompt engineering recomendadas
2. [ ] Refatorar `prompt.py` com novo template
3. [ ] Refatorar `sections/agent.py` com estrutura organizada
4. [ ] Refatorar `sections/execution.py` com padroes contextuais
5. [ ] Refatorar `sections/tool_prompts.py` com formatacao consistente
6. [ ] Validar com `evaluate_prompt_with_llm.py`
7. [ ] Documentar padroes em `docs/ai-guides/prompt-patterns.md`

---

## 7. Referencias

- Anthropic Prompt Engineering Best Practices
- System Prompt Design: 9 Patterns for Production LLMs
- LLM Best Practices: System Prompts Architecture
- User Requirements: Numered instructions, bullets, contextual patterns, organized sections, UPPERCASE emphasis
