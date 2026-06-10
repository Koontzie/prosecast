---
name: project-phase4-tagging
description: Phase 4 emotion/tone tagging pipeline — implementation status, Gideon dependency, tag schema, prompt design decisions
metadata:
  type: project
---

Phase 4 tagging pipeline implemented (2026-05-28). Status: working, partial validation.

**New files:**
- `prosecast/tag_generator.py` — sends each IR block to Gideon/Ollama (mistral:7b at `GIDEON_HOST:11434`); returns actor-facing tags; 0% error rate on sample book
- `prosecast/tag_mapper.py` — translates abstract tags to engine-specific render params at render time

**CLI flags added to main.py:**
- `--tag` — run tagging pass
- `--retag` — force re-tag already-tagged blocks
- `--tag-model` — Ollama model (default: mistral:7b)
- `--tag-dialogue-only` — skip narration blocks (faster)

**Tag schema:**
```json
"tags": {
  "action": "to evade direct answer",  // dialogue only; must start with "to "
  "emotion": "cautious reserve",
  "intensity": 0.3,
  "pace": "measured",
  "tag_method": "gideon-mistral"
}
```

**Critical prompt design:** uses 8 few-shot examples. The key discipline: action verbs must start with "to " (validated and rejected if not). Examples cover: subtext (surface text ≠ action), low-intensity (0.1-0.3), high-intensity urgency. Example outputs in the prompt must use `{{...}}` (escaped braces) not `{...}` — single braces caused a Python `KeyError` on `.format()`.

**Validation status:**
- Sample book (51 blocks): 51/51 tagged, 0 errors, 3.6s/block avg ✓
- Frankenstein (365 dialogue blocks): 28/365 tagged when Gideon went offline; resumed; pending full results
- Yumi and the Nightmare Painter: not yet run

**Gideon note:** Gideon (GIDEON_HOST) dropped mid-Frankenstein run — transient outage. Reconnect and resume with `--use-existing-ir --tag` — already-tagged blocks are skipped automatically.

**Why:** Chatterbox-Turbo is being set up on Gideon. For now, mistral:7b handles tagging. Tag corrections will eventually train a fine-tuned local model (same flywheel as attribution corrections).
