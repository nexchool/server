# Notification pipeline audit — 2026-09-14

Point-in-time. Scope: in-app inbox, push (FCM v1 + Expo), scheduled
notifications, and the Celery beat jobs behind them. Production was the
priority and every finding below was checked against the live environment
(`i-0cfd39b4452e87ef1`, account `774493573217`), not inferred from the tree.

**Headline: push notifications have never been delivered in production.** Two
independent faults each break the pipeline on their own, and neither surfaced
because every failure was absorbed silently.

---

## Evidence gathered from production

| Probe | Result |
|-------|--------|
| `is_fcm_configured()` inside `school-erp-api-1` | `False` |
| `list_active_tokens_for_user` ImportError lines in the worker log | **624**, across ~104 distinct `send_push_task` invocations |
| `send_push_task` outcomes in the worker log | every one: 3 retries, then `raised`. **Zero successes.** |
| `device_tokens` rows | **0** |
| `notification_recipients` by status | `read` 54, `sent` 23, **`pending` 30** |
| The 30 pending rows | all `academic_calendar`, all 2026-08-16, stuck ~4 weeks |
| Beat firings over 5.6 days | `retention.purge_audit_logs` **0**, `retention.advance_offboarding_stage` **0** |
| `FEE_OVERDUE` notification timestamps | 17:31 UTC = **23:01 IST** |
| Tenant `default` `feature_flags.notifications` | `true` (not the cause) |
| Firebase web config in the deployed admin-web bundle | present and correct |

---

## Root causes

### 1. `send_push_task` calls a function that does not exist — every push, every environment

`tasks/push_notifications.py:43` does a function-local
`from modules.devices.device_service import list_active_tokens_for_user`.
That function was deleted by the v2 rebuild (`643ac7b`) as part of a dead-code
sweep — its commit message lists it among ten symbols with no callers.

It had a caller. The sweep could not see it because the import sits inside the
task body rather than at module scope, so the module still imported cleanly and
Celery still registered the task. Every *invocation* raised `ImportError`,
`autoretry_for=(Exception,)` retried it three times, and it died.

This is the whole reason nobody noticed finding 2: the task never reached the
FCM call.

**Fixed** — function restored in `modules/devices/device_service.py`, with a
comment naming the caller so the next sweep sees it.

### 2. No FCM credentials in production

`FIREBASE_SERVICE_ACCOUNT_PATH` and `FIREBASE_SERVICE_ACCOUNT_JSON` are both
empty in `/home/ec2-user/.env.prod`. `is_fcm_configured()` returns `False` and
every send is skipped.

The `PATH` form cannot work in production at all: `server/.dockerignore`
excludes `secrets/`, so the JSON is never in the image, and
`docker-compose.prod.yml` bind-mounts nothing. Production must use the inline
`FIREBASE_SERVICE_ACCOUNT_JSON`.

**Not fixed by code** — operator action, see [Production remediation](#production-remediation).
Code now logs this once per send with the variable name, at ERROR, instead of
twice per device token at WARNING.

### 3. Three producers wrote fan-out rows and never dispatched them

`create_notification()` + `create_recipients()` only write rows. Nothing leaves
the server until `send_notification()` enqueues `dispatch_notification_task`.

| Producer | `create_recipients` | `send_notification` |
|----------|---------------------|---------------------|
| `modules/announcements/tasks.py` (publish + recall) | ✅ | ❌ |
| `modules/academics/calendar/activity.py` | ✅ | ❌ |
| `modules/student_leaves/services.py` | ✅ | ❌ |
| `modules/teachers/constraint_services.py` | ✅ | ✅ |

The three broken ones request `PUSH` in their channel list and deliver none of
it. They also publish no `INBOX_CREATED` event, so the SSE inbox never updates
live either — the notification appears only on a manual refresh. Those are the
30 `pending` rows in production.

`announcement_fan_out` was worse than the other two: it never committed, and it
runs inside a Celery task whose app-context teardown calls `session.remove()`.
Its notification and recipient rows were **rolled back entirely** — production
holds two published announcements and zero `announcement.published`
notifications.

**Fixed** — all three now commit, then enqueue dispatch, then publish the
realtime event.

### 4. Scheduled announcements enqueue before they commit

`process_scheduled_announcements` flipped `status` to `published`, called
`announcement_fan_out.delay()`, and committed after the loop.
`announcement_fan_out` opens with `if a.status != "published": return`. The
worker is a separate process on its own connection, so until the beat process
commits it reads `scheduled` — and drops the fan-out, logged as a routine
`fan_out skipped`.

**Fixed** — commit the batch, then enqueue. This also releases the
`SELECT FOR UPDATE` locks before the workers read those rows.

### 5. Push dies permanently for any user who was ever locked out

`tasks/push_notifications.py` compared `user.login_locked_until` — a
`DateTime(timezone=True)` column, so tz-aware — against a naive
`datetime.utcnow()`. That raises `TypeError`, which `autoretry_for` turns into
three retries and then silence. A lockout timestamp is never cleared, so one
comparison ends push for that user forever.

Production has 0 locked users today, so this had not yet fired. It was the only
`datetime.utcnow()` left in the notification paths.

**Fixed** — uses `core.school_time.utc_now()`.

### 6. Every failure was swallowed without a log

`NotificationDispatcher.dispatch` caught every strategy exception into
`results[ch] = False` with no logging. `InAppStrategy` did the same around its
insert. Absorbing the exception is right — one dead channel must not take the
others down — but absorbing it silently makes a broken channel
indistinguishable from a delivered one. This is why findings 1, 3 and 4 lasted.

**Fixed** — both now `logger.exception` with channel, user, tenant and type.
Covered by `tests/test_notification_dispatcher.py`.

### 7. Recurring jobs were anchored to the last deploy, not to the clock

Every beat entry was an interval float, and beat's state file is
`/tmp/celerybeat-schedule` — inside a container that `docker compose pull && up -d`
replaces. So `86400.0` meant "a day after the last deploy" and `604800` meant
"never" on any repo that deploys more than weekly.

Consequences measured in production: the two weekly retention jobs had never
run, and `FEE_OVERDUE` notifications were reaching parents at **23:01 IST**
because that is when the last deploy happened.

**Fixed** — everything rarer than hourly is now a `crontab()`, and
`celery.conf.timezone` is `Asia/Kolkata` so the hours read as the school's
clock. Sub-hourly polls stay intervals, which is correct for them.

| Job | Now runs (IST) |
|-----|----------------|
| `process-overdue-fees-daily` | 09:00 |
| `subscription-send-payment-reminders` | 09:30 |
| `retention-purge-notification-logs` | 01:15 |
| `retention-purge-expired-sessions` | 01:30 |
| `subscription-suspend-after-grace` | 03:00 |
| `announcements-sweep-orphan-attachments` | 02:45 |
| `retention-purge-audit-logs` | Sun 02:00 |
| `retention-advance-offboarding` | Sun 02:30 |

### 8. Two N+1 queries on the paths that scale with the tenant

- `process_notification_chunk` ran one `NotificationRecipient` query **per
  recipient**. Measured at 28 queries for 12 recipients; at the top of the
  scale contract that is 15,000 round trips for one announcement.
- `_serialize_list_item` ran one query **per notification** on every inbox page
  load, up to the 100-item maximum, for every signed-in user.

**Fixed** — both batch into one query. Locked by
`tests/test_notification_query_shape.py`, which counts statements.

---

## Production remediation

Ordered. Steps 1–2 are the operator's; step 3 is the deploy.

### 1. Generate a service-account key for production

The local key (`server/secrets/firebase-service-account.json`,
`firebase-adminsdk-fbsvc@nexchool-def76.iam.gserviceaccount.com`) *would* work —
same project, and service accounts are not environment-specific. Generate a
separate one anyway, so a laptop leak can be revoked without taking production
push down.

1. Firebase Console → project **nexchool-def76** → ⚙ → **Project settings**
2. **Service accounts** tab → **Generate new private key** → Generate key
3. A JSON file downloads. It contains a live private key — do not commit it.
4. Flatten it to one line:
   ```bash
   jq -c . ~/Downloads/nexchool-def76-firebase-adminsdk-*.json
   ```

### 2. Put it in the production environment

On the instance (`aws ssm start-session --target i-0cfd39b4452e87ef1`, then
`sudo -i`):

1. Edit `/home/ec2-user/.env.prod` and set the flattened JSON as
   `FIREBASE_SERVICE_ACCOUNT_JSON=` — single-quoted is safest; the private key's
   own `\n` escapes stay as the two characters backslash-n. Leave
   `FIREBASE_SERVICE_ACCOUNT_PATH` empty.
2. Recreate the services that read it:
   ```bash
   cd /home/ec2-user
   docker compose -f docker-compose.prod.yml --env-file .env.prod up -d api celery-worker celery-beat
   ```
3. Verify:
   ```bash
   docker exec school-erp-api-1 python -c \
     "from modules.notifications.firebase_service import is_fcm_configured; print(is_fcm_configured())"
   ```
   Must print `True`.

### 3. Deploy the code fixes

Everything in "Root causes" above except #2 is code, on `develop`. It reaches
production when `develop` merges to `main` (server `main` push = deploy +
`flask db upgrade`). No migration is involved.

### 4. Mobile push needs a separate credential, on Expo — not here

The server sends Expo tokens (`ExponentPushToken[...]`) through Expo's push
API, not through the credential above. Android delivery for those requires the
**FCM v1 service account uploaded to EAS**:

```bash
cd client && eas credentials      # Android → FCM V1 service account → upload
```

iOS additionally needs an APNs key on EAS. `EXPO_ACCESS_TOKEN` in `.env.prod`
is optional and only raises Expo's rate limit.

The credential in step 1 covers **admin-web / web push only**.

### 5. There will still be no device tokens

`device_tokens` is empty, and push has nowhere to go until it is not. In
admin-web a signed-in user must click through the notification permission
prompt (`Header.tsx` / `NotificationPermissionBanner.tsx`) — it is
user-gesture-gated, as browsers require. Registering one token and re-running
the verification in step 2 is the end-to-end check.

### 6. Leave the 30 stuck rows alone

They are `academic_calendar` notifications from 2026-08-16. The fix does not
retroactively dispatch them, and it should not — pushing month-old calendar
changes to phones would be worse than the silence. They remain visible in the
in-app inbox, which is where they have been all along.

---

## Deliberately not changed

- **`/api/notifications/send` and `/send-bulk` require `finance.manage`**
  (`modules/notifications/routes.py`). Sending a general notification should
  not need finance rights; `announcement.create` is the business-correct
  permission. Not changed here because narrowing or widening authorization on a
  live system is its own decision with its own blast radius. Registered as
  debt 66.
- **A transient push failure is lost.** `deliver_to_tokens` retries once with
  no backoff — microseconds later, so a network blip fails both attempts — and
  then returns normally, so Celery's own `retry_backoff` never engages.
  Registered as debt 65.
- **`PushStrategy` always returns `True`**, so `process_notification_chunk`'s
  `any(results.values())` marks a recipient `sent` whenever `PUSH` is among the
  channels, regardless of what happened. Recipient status is not evidence of
  delivery. Folded into debt 65.

---

## Tests added

| File | Locks in |
|------|----------|
| `tests/test_notification_delivery_pipeline.py` | every bulk producer commits then dispatches; the scheduled-announcement commit/enqueue ordering; push survives a once-locked user and still skips a currently-locked one |
| `tests/test_notification_query_shape.py` | statement counts for fan-out and inbox serialization |
| `tests/test_beat_schedule.py` | nothing rarer than hourly is an interval; parent-facing jobs run in waking hours; schedule timezone is the school timezone |
| `tests/test_notification_dispatcher.py` (added case) | a failing channel leaves a log naming it |

Every announcements test monkeypatches `_enqueue_fan_out` to a no-op, which is
why the fan-out body — missing commit, missing dispatch — was never executed by
the suite. The new tests call the task bodies directly.

All fourteen were confirmed to fail against the unfixed code and pass against
the fixed code, by stashing the source changes and re-running.

### A trap these tests hit first — do not call `create_app()` in a test

`app.py:561` builds the module-level app, and `create_app()` calls
`init_celery(app)`, which assigns the **module-global `_celery`** — whose
`ContextTask.__call__` enters `with app.app_context()` for every task body.

A second app built inside a test therefore repoints every later Celery task at
that app's engine registry — the real database, not the test's transactional
connection. The first version of `test_beat_schedule.py` did this, and the
damage landed on the *notification* tests that sort after it alphabetically:
`send_push_task` returned `no_user` and `process_notification_chunk` left
recipients at `pending`, because neither could see rows that existed only in
another connection's transaction.

It reproduced only under `-p no:randomly` (file order) and never when the
notification files ran alone, which is exactly what makes it expensive: the
failure names the victim, not the culprit. Read the live instance through
`get_celery()` instead. Registered as debt 67.
