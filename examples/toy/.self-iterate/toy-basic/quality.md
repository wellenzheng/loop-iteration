# Harness quality rubric

Score the agent's harness file(s) (the prompt/instructions shown) on these dimensions, 0-10:

- **clarity** (0-10): 10 = unambiguous, well-structured instructions a model can follow directly;
  0 = vague, contradictory, or confusing.
- **no_overfit** (0-10): AUTO-DETECTED programmatically (not LLM-scored). 10 = no eval-specific content
  (expected answers or verbatim queries) found in the harness; 0 = the harness hardcodes eval answers.
  Reliable even when the LLM judge is unavailable.
- **maintainability** (0-10): 10 = concise, readable, easy to edit; 0 = bloated, repetitive, or brittle.
