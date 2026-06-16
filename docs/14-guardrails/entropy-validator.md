# Entropy Validator

Detects low-confidence responses where the model is heavily hedging without strong chunk support. Routes these to abstain rather than showing an uncertain answer to the user.

---

## What It Checks

Two signals combined:

1. **Hedge density** — ratio of hedging phrases to total sentences
2. **Chunk support score** — average reranked chunk score for the query

Both must be unfavorable to fail: high hedging AND weak chunk support.

---

## Hedge Phrases

```python
HEDGE_PHRASES = [
    "i'm not sure", "i don't know", "i cannot", "i'm unable to",
    "it's unclear", "this is uncertain", "i don't have enough",
    "i cannot confirm", "it may be", "it might be", "possibly",
    "it seems like", "i think but", "you should check",
]
```

Hedge density = `hedge_phrase_count / sentence_count`.

---

## Entropy Score

```python
def compute_entropy_score(response: str, chunks: list[ScoredChunk]) -> float:
    hedge_density = count_hedges(response) / max(count_sentences(response), 1)
    avg_chunk_score = sum(c.score for c in chunks) / max(len(chunks), 1)

    # High hedge_density + low avg_chunk_score = high entropy (bad)
    # Scale: 0.0 (confident, well-supported) → 1.0 (very uncertain, unsupported)
    entropy = hedge_density * (1.0 - avg_chunk_score)
    return entropy
```

---

## Thresholds

| `ENTROPY_THRESHOLD` | Default | Config key |
|---|---|---|
| Fail threshold | `0.65` | `ENTROPY_THRESHOLD` in `app.settings` |

Entropy above threshold → validator fails → abstain (not escalate).

---

## Failure Outcome

| Condition | `should_escalate` | Routing |
|---|---|---|
| `entropy > ENTROPY_THRESHOLD` | `False` | Abstain |

Entropy failure is not escalated to HITL — an uncertain response is replaced with the safe fallback message. HITL is reserved for accuracy failures (citation, price).

---

## Calibration

| Scenario | Expected entropy |
|---|---|
| Strong retrieval, confident answer | `0.05 – 0.20` |
| Partial retrieval, some uncertainty | `0.30 – 0.55` |
| Poor retrieval, heavy hedging | `0.65 – 0.90` |

Lower `ENTROPY_THRESHOLD` → more responses abstained (conservative). Higher → more uncertain responses pass through.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Too many abstentions | Threshold too low or poor vault coverage | Raise `ENTROPY_THRESHOLD`; also check vault ingest coverage |
| Hedged responses not caught | Threshold too high | Lower `ENTROPY_THRESHOLD` |
| False positives on "may" / "might" | Common hedges in normal prose | Remove low-signal words from `HEDGE_PHRASES` |

---

## Related Docs

- [Citation Validator](citation-validator.md)
- [ExactMatch Validator](exactmatch-validator.md)
- [Dynamic Settings](../16-configuration-reference/dynamic-settings.md) — `ENTROPY_THRESHOLD`
