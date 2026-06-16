# ExactMatch Validator

Verifies that high-stakes values in the response — prices, dates, and named entities — match what appears verbatim in the retrieved chunks.

---

## What It Checks

| Value type | Method | Tolerance |
|---|---|---|
| Prices (`$99`, `99.00`, `USD 99`) | Regex extract → compare against chunk text | ±$0.01 |
| Dates (`2026-06-14`, `June 14`) | Normalize to ISO → compare against chunks | Exact match after normalization |
| Named nouns (products, plans, features) | NER extraction → substring search in chunks | Case-insensitive substring |

---

## Implementation

```python
class ExactMatchValidator:
    def validate(self, response: str, chunks: list[ScoredChunk]) -> ValidatorResult:
        chunk_text = " ".join(c.text for c in chunks)

        # Price check
        response_prices = extract_prices(response)
        chunk_prices = extract_prices(chunk_text)
        for price in response_prices:
            if not any(abs(price - cp) <= 0.01 for cp in chunk_prices):
                return ValidatorResult(
                    passed=False,
                    reason=f"Price ${price} not found in retrieved chunks",
                    should_escalate=True   # Financial accuracy risk
                )

        # Date check
        response_dates = extract_dates(response)
        for date in response_dates:
            if date.isoformat() not in chunk_text:
                return ValidatorResult(
                    passed=False,
                    reason=f"Date {date} not found in retrieved chunks",
                    should_escalate=False
                )

        return ValidatorResult(passed=True)
```

---

## Failure Outcomes

| Failure type | `should_escalate` | Routing | Reason |
|---|---|---|---|
| Price mismatch | `True` | HITL | Financial accuracy — cannot abstain with wrong price |
| Date mismatch | `False` | Abstain | Lower risk — safe to show fallback |
| Named entity not in chunks | `False` | Abstain | Hallucinated product/feature name |

Price failures always escalate because showing a wrong price in a sales context causes customer harm.

---

## Price Extraction Patterns

```python
PRICE_PATTERNS = [
    r'\$[\d,]+(?:\.\d{2})?',        # $99.00, $1,299
    r'USD\s*[\d,]+(?:\.\d{2})?',    # USD 99.00
    r'[\d,]+(?:\.\d{2})?\s*USD',    # 99.00 USD
]
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| HITL triggered on correct prices | Price format mismatch (`$99` vs `99.00`) | Normalize price format in product catalog |
| Date false positives | Relative dates ("today", "next week") triggering | Exclude relative date patterns from extraction |
| Named entity false positives | NER misclassifying common words | Tune NER confidence threshold |

---

## Related Docs

- [Citation Validator](citation-validator.md)
- [Entropy Validator](entropy-validator.md)
- [HITL Fallback](hitl-fallback.md)
- [Product Catalog](../11-product-catalog/README.md)
