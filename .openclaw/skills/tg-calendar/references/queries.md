# Queries/snippets for tg-calendar

Use as templates; adapt to task and keep bot-compatible semantics.

## 1) Resolve user profile context

```sql
select
  tg_id,
  max_id,
  coalesce(nullif(first_name, ''), nullif(username, ''), tg_id::text, max_id::text) as display_name,
  time_zone,
  language_code
from public.tg_users
where tg_id = :tg_id or max_id = :max_id
limit 1;
```

## 2) List events in local date range (rendered in user tz)

```sql
select
  e.id,
  e.description,
  e.emoji,
  e.start_at,
  e.stop_at,
  (e.start_at at time zone :tz_name) as start_local,
  (e.stop_at  at time zone :tz_name) as stop_local,
  e.single_event, e.daily, e.weekly, e.monthly, e.annual_day, e.annual_month
from public.events e
where (e.tg_id = :tg_id or e.max_id = :max_id)
  and e.start_at >= :from_utc
  and e.start_at <  :to_utc
order by e.start_at;
```

## 3) Create one-time event from local datetime

```sql
with u as (
  select tg_id, max_id
  from public.tg_users
  where tg_id = :tg_id
), ins as (
  insert into public.events (
    description, emoji,
    start_at, stop_at, start_time,
    single_event, daily, weekly, monthly, annual_day, annual_month,
    tg_id, creator_tg_id,
    max_id, creator_max_id
  )
  select
    :description,
    nullif(:emoji, ''),
    (:start_local::timestamp at time zone :tz_name),
    case when :stop_local is null then null else (:stop_local::timestamp at time zone :tz_name) end,
    ((:start_local::timestamp at time zone :tz_name) at time zone 'UTC')::time,
    true, false, null, null, null, null,
    u.tg_id, u.tg_id,
    u.max_id, u.max_id
  from u
  returning id
)
insert into public.event_participants (event_id, participant_tg_id, participant_max_id)
select ins.id, :tg_id, (select max_id from public.tg_users where tg_id = :tg_id)
from ins;
```

## 4) Update event core fields

```sql
update public.events
set
  description = :description,
  emoji = :emoji,
  start_at = (:start_local::timestamp at time zone :tz_name),
  stop_at  = case when :stop_local is null then null else (:stop_local::timestamp at time zone :tz_name) end,
  start_time = ((:start_local::timestamp at time zone :tz_name) at time zone 'UTC')::time,
  single_event = :single_event,
  daily = :daily,
  weekly = :weekly,
  monthly = :monthly,
  annual_day = :annual_day,
  annual_month = :annual_month
where id = :event_id;
```

## 5) Replace participants for event

```sql
delete from public.event_participants where event_id = :event_id;
-- then bulk insert rows with participant_tg_id/participant_max_id
```

## 6) Cancel one occurrence of recurrent event

```sql
insert into public.canceled_events (cancel_date, event_id)
values (:cancel_date, :event_id);
```

## 7) Quick “useful info” digest from existing events

```sql
select
  e.id,
  e.description,
  e.emoji,
  e.start_at at time zone :tz_name as start_local,
  e.stop_at  at time zone :tz_name as stop_local
from public.events e
where (e.tg_id = :tg_id or e.max_id = :max_id)
order by e.start_at desc
limit 100;
```

Use this output to summarize recurring commitments, deadlines, and context-relevant notes embedded in descriptions.
