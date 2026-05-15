# Decision Tree: Modificar Segurança do Browser

## Pergunta inicial
> Preciso ajustar como o agente interage com o browser ou o que é considerado seguro/perigoso.

---

## Passo 1: Identificar o tipo de mudança

### Se é sobre quais ações exigem aprovação:
→ **Modificar BrowserActionArbiter**
- Arquivo: `application/services/browser_action_arbiter.py`

### Se é sobre dados sensíveis em eventos:
→ **Modificar BrowserCooperation**
- Arquivo: `application/services/browser_cooperation.py`

### Se é sobre modos de cooperação:
→ **Modificar BrowserCooperation + BrowserActionArbiter**

---

## Passo 2: Modificar BrowserActionArbiter

### Para adicionar novo modo:
1. Adicionar a `BROWSER_COOPERATION_MODES` em `browser_cooperation.py:25`
2. Adicionar branch em `BrowserActionArbiter.decide()` @ `browser_action_arbiter.py:59-84`

### Para ajustar o que é destrutivo:
1. Modificar regex `_DESTRUCTIVE_RE` @ `:24`
2. Modificar `_is_destructive()` @ `:142`
3. Modificar `_requires_explicit_confirmation()` @ `:158`

### Para ajustar cooldowns:
1. Modificar `HUMAN_ACTIVITY_COOLDOWN_SECONDS` @ `:22`
2. Modificar `DESTRUCTIVE_ACTIVITY_COOLDOWN_SECONDS` @ `:23`

---

## Passo 3: Modificar BrowserCooperation (redação)

### Para adicionar novo tipo de dado sensível:
1. Adicionar a `_SENSITIVE_FIELD_RE` @ `browser_cooperation.py:45`
2. Adicionar query key a `_SENSITIVE_QUERY_KEYS` @ `:50`

### Para mudar política de retenção:
1. Modificar `DEFAULT_COOPERATION_POLICY` @ `:35`

---

## Passo 4: Testes

1. `tests/test_browser_cooperation.py`
2. `tests/integration/test_browser_tools.py`
3. Verificar: cada mudança no arbiter deve ter teste de decisão correspondente

---

## Passo 5: Documentação

1. Atualizar ADR 0013 (Browser Workspace)
2. Atualizar `docs/ai-guides/backend/browser-action-arbiter.md`
3. Atualizar `docs/ai-guides/backend/browser-cooperation.md`

---

## Checklist

- [ ] Regex testado contra falsos positivos
- [ ] Novo modo tem branch no arbiter
- [ ] Cooldowns são >= 0
- [ ] Testes de browser passam
- [ ] Documentação atualizada
