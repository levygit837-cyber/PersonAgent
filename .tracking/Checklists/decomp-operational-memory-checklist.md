# Decomposition Checklist: operational_memory.py

## Baseline (2026-05-25)
- ruff: All checks passed!
- test_chat_operational_memory.py + test_chat_memory_recall.py: 28 passed
- tests/integration/memory/: 43 passed
- tests/unit/: 1769 passed, 1 failed (known: test_agent_state_overlays_are_compact), 2 skipped

## Slice 1 — Extract extraction surface into `operational_memory/extraction.py`
- [ ] Phase A: Create branch from main
- [ ] Phase B: Map surface (methods, constants, imports, call sites)
- [ ] Phase B: Create extraction module
- [ ] Phase B: Wire into parent (instantiate in __init__, update call sites)
- [ ] Phase B: Delete originals
- [ ] Phase B: Run ruff check --fix
- [ ] Phase B: Write tests (tests/unit/test_operational_memory_extraction.py, 15+ cases)
- [ ] Phase C: Validation gates (ruff, mypy, tests >= baseline + new)
- [ ] Phase D: Commit and push
- [ ] Phase E: Open PR

## Slice 2 — Extract recall surface into `operational_memory/recall.py`
- [ ] Phase A: Create branch from main
- [ ] Phase B: Map surface
- [ ] Phase B: Create recall module
- [ ] Phase B: Wire into parent
- [ ] Phase B: Delete originals
- [ ] Phase B: Run ruff check --fix
- [ ] Phase B: Write tests (tests/unit/test_operational_memory_recall.py, 15+ cases)
- [ ] Phase C: Validation gates
- [ ] Phase D: Commit and push
- [ ] Phase E: Open PR

## Slice 3 — Extract capture surface into `operational_memory/capture.py`
- [ ] Phase A: Create branch from main
- [ ] Phase B: Map surface
- [ ] Phase B: Create capture module
- [ ] Phase B: Wire into parent
- [ ] Phase B: Delete originals
- [ ] Phase B: Run ruff check --fix
- [ ] Phase B: Write tests (tests/unit/test_operational_memory_capture.py, 15+ cases)
- [ ] Phase C: Validation gates
- [ ] Phase D: Commit and push
- [ ] Phase E: Open PR
