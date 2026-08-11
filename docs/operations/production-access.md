# Production Access and Database Operations

How to reach the production environment and operate its database.

Everything here was verified against the live environment on 2026-08-11. Where a
step has a trap, the trap is written down rather than left to be rediscovered.

---

# The Environment

| Thing | Value |
|-------|-------|
| AWS account | `774493573217`, region `ap-south-1` |
| EC2 instance | `i-0cfd39b4452e87ef1` |
| RDS instance | `nexchool-prod`, PostgreSQL **17.9**, not publicly accessible |
| Compose file | `/home/ec2-user/docker-compose.prod.yml` |
| Environment file | `/home/ec2-user/.env.prod` |

The database is reachable only from the EC2 instance. There is no path to it
from a laptop, by design.

---

# Access

## Use the right AWS profile

The `default` profile carries a key that was deactivated during the June 2026
IAM cutover. Any command that uses it fails, and the failure does not say
"wrong profile":

```
An error occurred (403) when calling the StartSession operation:
Server authentication failed: <UnauthorizedRequest><message>Forbidden.</message></UnauthorizedRequest>
```

That is a dead credential, not a missing permission. Always use
`nexchool-admin`:

```bash
export AWS_PROFILE=nexchool-admin
```

## Open a shell

```bash
AWS_PROFILE=nexchool-admin aws ssm start-session --target i-0cfd39b4452e87ef1
```

If the CLI is unavailable, the AWS Console gives the same shell:
**Systems Manager → Session Manager → Start session**.

## Become root before doing anything

Session Manager logs in as `ssm-user`. Two things block that user:

- `/home/ec2-user` is mode `drwx------`, owned by `ec2-user` — `cd` fails with
  `Permission denied`.
- `ssm-user` is not in the `docker` group; only `ec2-user` is. So `docker`
  fails even once the directory is reachable.

`ssm-user` has passwordless sudo, so the first command in every session is:

```bash
sudo -i
```

This is also why commands sent through `aws ssm send-command` behave
differently from an interactive session — those run as root already.

---

# Common Operations

All of these assume `sudo -i` and `cd /home/ec2-user`.

## Create a super admin

Needed on any environment with no accounts — a freshly rebuilt database has
none, and there is no other way to log in.

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python -m scripts.create_super_admin
```

Prompts for email, password and name. It also reads `SUPER_ADMIN_EMAIL`,
`SUPER_ADMIN_PASSWORD` and `SUPER_ADMIN_NAME` from the environment, but do not
pass the password that way through `send-command` — the parameters are recorded
in CloudTrail and the SSM command history. Type it into the interactive prompt.

## Check the migration state

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api flask db current
```

## Read logs

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs api --tail 50
```

---

# How Deploys Apply Migrations

A push to `main` triggers `.github/workflows/ec2-deploy.yml`, which builds the
image, pushes it to ECR, and over SSM runs `docker compose pull` and
`up -d` on the instance. **The workflow itself does not run migrations.**

Migrations run when the container starts. `Dockerfile` sets
`ENTRYPOINT ["./docker-entrypoint.sh"]`, which runs `startup.sh`, which waits
for Postgres, runs `flask db upgrade`, runs the seeds, and then starts Gunicorn.

Three consequences worth holding on to:

- **A failed migration is an outage, not a rollback.** `startup.sh` runs under
  `set -eu`, so a failing `flask db upgrade` kills the container — after the new
  image has already been deployed.
- **Only `api` migrates.** `celery-worker` and `celery-beat` override
  `entrypoint:` in the compose file, so they never race the migration.
- **`SKIP_DB_MIGRATE=1` and `SKIP_DB_SEED=1`** disable the two phases. Neither
  is set in production.

`startup.sh` also widens `alembic_version.version_num` to `VARCHAR(255)` before
upgrading, and pre-creates the table at that width on a fresh database. Some
revision ids exceed Alembic's default `VARCHAR(32)`, and the whole chain runs in
one transaction, so without this a fresh database aborts partway.

---

# Database Operations

## Match the client to the server version

Production is PostgreSQL **17.9**. `pg_dump` refuses to dump a server newer than
itself, and `pg_restore` cannot read an archive from a newer one. A Homebrew
PostgreSQL 14 client cannot touch production, and neither can a `postgres:16`
container.

Run the client in a container of the right major version:

```bash
set -a; . /home/ec2-user/.env.prod; set +a
docker run --rm -e DATABASE_URL="$DATABASE_URL" -v /home/ec2-user/backups:/out \
  postgres:17-alpine sh -c 'pg_dump "$DATABASE_URL" -Fc -f /out/prod.dump'
```

Sourcing `.env.prod` and passing `DATABASE_URL` through the environment keeps
the credential out of the command line, the terminal and the SSM command log.

## Verify a dump before trusting it

A dump nobody has restored is a hope, not a backup. Restore it into a scratch
container and count what came back:

```bash
docker run -d --name pgverify -e POSTGRES_PASSWORD=verify postgres:17-alpine
docker exec pgverify psql -U postgres -qc "CREATE DATABASE verify"
docker cp /home/ec2-user/backups/prod.dump pgverify:/tmp/prod.dump
docker exec pgverify pg_restore -U postgres -d verify --no-owner --no-privileges /tmp/prod.dump
docker exec pgverify psql -U postgres -d verify -tAc "select count(*) from tenants"
docker rm -f pgverify
```

Remove the scratch container when finished. It holds a full copy of production
data.

## Rebuild the database from migrations

Destructive. Everything in the database is lost; only a verified dump gets it
back. Take and verify one first.

```bash
# 1. stop the app so nothing reconnects mid-wipe
docker compose -f docker-compose.prod.yml --env-file .env.prod stop api celery-worker celery-beat

# 2. drop and recreate the schema
set -a; . /home/ec2-user/.env.prod; set +a
docker run --rm -e DATABASE_URL="$DATABASE_URL" postgres:17-alpine sh -c \
  'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
     -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()" \
     -c "DROP SCHEMA public CASCADE" -c "CREATE SCHEMA public"'

# 3. start the app — startup.sh rebuilds the schema from migrations
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d api celery-worker celery-beat
```

`DROP SCHEMA` rather than `DROP DATABASE`: a session cannot drop the database it
is connected to, and the schema drop achieves the same result.

Afterwards the database has the schema and the seeded permissions but **no
accounts**. Create a super admin before anything else, then onboard tenants
through the panel.

---

# History

The production database was deliberately wiped on **2026-08-11**, discarding
three tenants (`demo`, `mts`, `default`), 168 students and 184 users. The data
was test and demo content and was judged disposable ahead of the v2 migration.

The dump taken beforehand — 582,500 bytes, sha256 `928b5d77536e492f89ffe72e42b4d21f4061507b9957fafea3a83dbe4d65e2f8` —
was verified to restore before the wipe. It lives at
`/home/ec2-user/backups/prod.dump` on the instance, and is the only copy.

Wiping ahead of the v2 deploy removed the migration risk that motivated it: the
backfill steps in migrations 079–105 now run against empty tables, so
`scripts/backfill_people.py` has nothing to backfill.
