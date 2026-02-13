---
name: tg-calendar
description: Use the ClawPlanner Postgres/Supabase database directly to create, read, update, reschedule, and delete calendar events, participants, and user notes with bot-compatible semantics (UTC storage, user timezone, recurrence, tg/max IDs, user_id links). Trigger when user asks about calendar/events/reminders/participants/notes, OR sends/forwards text where date/time/description can be inferred (treat as create-event intent). If date is present but time is missing, propose a reasonable default time and ask confirmation. Also use when user asks to fetch timezone/language/name from tg_users, summarize useful info from existing events/notes, or debug reminder mismatch.
---

# tg-calendar

Operate the existing planner DB used by ClawPlanner.

## Core behavior

- Treat forwarded/quoted plain text containing actionable date/time/description as an event-creation request.
- If date is known but time is absent, suggest a sensible default (e.g., 10:00 for daytime tasks, 19:00 for evening activities) and ask for confirmation before writing.
- Resolve and use profile context from `public.tg_users`: display name, `time_zone`, `language_code`, and platform ids (`tg_id`, `max_id`).
- Keep writes compatible with bot logic in `database/db_controller.py`, `handlers/events.py`, and `cron_handler.py`.

## Time and identity rules

- Store all datetimes in UTC in DB; show time to users in their timezone (`tg_users.time_zone`, fallback `config.DEFAULT_TIMEZONE_NAME`).
- Keep tg/max linkage consistent:
  - events: `tg_id`, `creator_tg_id`, `max_id`, `creator_max_id`
  - participants: `participant_tg_id`, `participant_max_id`
- For edits/reschedules, preserve recurrence semantics or follow bot behavior for creating a shifted copy when requested as “+1 hour / tomorrow”.

## CRUD expectations

### Create event

1. Resolve user row in `tg_users` and effective timezone/language.
2. Parse title/description/date/time/optional end time/participants from user text.
3. Convert local datetime to UTC.
4. Insert into `events` with correct recurrence flags and IDs.
5. Insert owner (and other users if requested) into `event_participants`.

### Read/list events

- Use the same recurrence expansion semantics as the bot (see `database/db_controller.py`).
- When summarizing “notes/events”, extract useful context primarily from `events.description`, `emoji`, time ranges, recurrence, and participant rows.

### Update event

- Support changing description, emoji, start/stop times, recurrence, and participants.
- Use bot-compatible updates so reminder selection remains correct.

### Reschedule

- Handle explicit shifts (`+1 hour`, `tomorrow`, specific new datetime).
- If user asks to move a single upcoming occurrence of recurrent event, follow cancel/clone semantics used by bot (`canceled_events` + new/specific event handling as applicable).

### Delete/cancel

- Delete single non-recurrent events directly.
- For recurrent events, support canceling one occurrence when asked.

## Notes expectations

- Support notes CRUD via `tg_note` table through bot semantics:
  - list notes, open note, create note, edit note, delete note
- Resolve note owner by user row id (not external tg/max id) using DB controller helpers.
- Keep note text validation consistent with bot limits/behavior.

## Required code references

- `database/db_controller.py` (source of truth for semantics)
- `handlers/events.py` (event UI flow and intent mapping)
- `handlers/notes.py` (notes UI flow and state machine)
- `cron_handler.py` (reminder selection)
- `database/models/user_model.py`
- `database/models/event_models.py`
- `database/models/note_model.py`

## References

- Read `references/schema.md` for table/column map.
- Read `references/queries.md` for safe SQL templates.
