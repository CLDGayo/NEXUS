# Citation Validator

Checks that every `[n]` citation in the generated response refers to a chunk that was actually retrieved and reranked.

---

## What It Checks

1. **Index range** — all `[n]` values are ≤ `len(reranked_chunks)`
2. **No phantom citations** — `[n]` indices not skipped (e.g., response cites `[1][3]` but only 2 chunks returned)
3. **Minimum coverage** — factual claim sentences contain at least one citation
4. **No bare claims** — sentences stating prices, dates, or product names must have a `[n]` attached

---

## Implementation

```python
class CitationValidator:
    def validate(self, response: str, chunks: list[ScoredChunk]) -> ValidatorResult:
        cited_indices = {int(m) for m in re.findall(r'\[(\d+)\]', response)}
        max_valid = len(chunks)

        out_of_range = {i for i in cited_indices if i > max_valid or i < 1}
        if out_of_range:
            return ValidatorResult(
                passed=False,
                reason=f"Phantom citations: {out_of_range}",
                should_escalate=True
            )

        if not cited_indices and self._has_factual_claims(response):
            return ValidatorResult(
                passed=False,
                reason="Unsupported factual claims — no citations",
                should_escalate=False
            )

        return ValidatorResult(passed=True)
```

---

## Failure Outcomes

| Failure type | `should_escalate` | Routing |
|---|---|---|
| Phantom citation indices | `True` | HITL |
| Zero citations on factual response | `False` | Abstain |

---

## Citation Format Enforced in Generation

The `generate_node` system prompt includes explicit citation instructions:

```
After each factual claim, cite the source chunk using [n] notation.
Example: "The Pro plan costs $99/month [1]."
Only cite chunk numbers that were provided in your context (1 to {n}).
Never invent citation numbers.
```

CitationValidator is a backstop for when this instruction is not followed.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| All responses abstaining | Model not generating citations | Check system prompt citation instruction |
| `[1]` but only 0 chunks retrieved | Reranker dropped everything below floor | Lower `RERANK_CONFIDENCE_FLOOR` |
| False positive phantom detection | Response uses `[1]` as list marker not citation | Improve regex to exclude list contexts |

---

## Related Docs

- [ExactMatch Validator](exactmatch-validator.md)
- [Entropy Validator](entropy-validator.md)
- [Guardrails README](README.md)
- [Stage 5 — Generation](../02-rag-pipeline/stage-5-generation.md)
