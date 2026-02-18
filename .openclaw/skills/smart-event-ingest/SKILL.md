---
name: smart-event-ingest
description: Extract calendar events from noisy OCR/PDF/poster/voice text and return strict JSON for bot ingestion. Use when text is messy, incomplete, or ambiguous; ask one focused clarification question instead of guessing.
---

Return output as **JSON only**.

## Output contract

If confident:

```json
{
  "status": "ok",
  "events": [
    {
      "date": "YYYY-MM-DD",
      "start_time": "HH:MM",
      "end_time": "HH:MM|null",
      "description": "string",
      "address": "string",
      "recurrent": "never|daily|weekly|monthly|annual"
    }
  ]
}
```

If not confident / missing key fields:

```json
{
  "status": "clarify",
  "question": "One short question that resolves the ambiguity"
}
```

## Rules

- Prefer **precision over guessing**.
- Never invent a date/time/place if absent or conflicting.
- If year is missing, pick nearest future valid date.
- Keep `description` meaningful (not `"Событие"` unless absolutely unavoidable).
- Put venue/address into `address`, not into `description`.
- Ask at most one clarification question per turn.
- Support Russian and English input.

## Clarification priorities

Ask for the first missing/ambiguous field in this order:
1. Date
2. Start time
3. What exactly the event is (description)
4. Place (if needed)
