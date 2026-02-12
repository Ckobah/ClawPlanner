# ClawPlanner DB schema (calendar-relevant)

## public.tg_users

Main profile/identity table used by bot and planner.

Important columns:
- `id` int PK
- `tg_id` bigint unique nullable
- `max_id` bigint unique nullable
- `username` text nullable
- `first_name` text nullable
- `last_name` text nullable
- `language_code` varchar(5) nullable
- `time_zone` varchar(50) nullable
- `is_active` bool
- `is_chat` bool
- `created_at`, `updated_at`

Use this table to resolve:
- display name (`first_name` → `username` → id fallback)
- timezone for rendering and local parsing
- language preference defaults
- tg/max linkage for writes

## public.events

Event table with UTC storage and recurrence flags.

Important columns:
- `id` int PK
- `description` text not null
- `emoji` varchar(8) nullable
- `start_time` time not null (UTC time-of-day)
- `start_at` timestamptz not null (UTC)
- `stop_at` timestamptz nullable (UTC)
- `single_event` bool
- `daily` bool
- `weekly` int nullable
- `monthly` int nullable
- `annual_day` int nullable
- `annual_month` int nullable
- `tg_id`, `max_id` bigint nullable
- `creator_tg_id`, `creator_max_id` bigint nullable
- `created_at` timestamptz

## public.event_participants

Participants per event.

Important columns:
- `id` int PK
- `event_id` int FK -> `events.id`
- `participant_tg_id` bigint nullable
- `participant_max_id` bigint nullable
- `created_at`

## public.canceled_events

Stores canceled single occurrences for recurrent events.

Important columns:
- `id` int PK
- `cancel_date` date not null
- `event_id` int FK -> `events.id`

## public.user_relations

Maps user-to-user contact relations for participant selection.

Columns:
- `user_id` int FK -> `tg_users.id`
- `related_user_id` int FK -> `tg_users.id`
