# TLS certificates — `nexchool.in`

**Status:** wildcard, DNS-01, fully automated. Since 2026-09-15, onboarding a
school requires **no certificate work of any kind**.

Read this before touching DNS, nginx TLS, or certbot on the production box.
Production access itself is documented in `production-access.md`.

---

## The contract

One certificate lineage, `nexchool.in`, covering two names:

```
nexchool.in
*.nexchool.in
```

`*.nexchool.in` covers every tenant subdomain plus `api`, `panel`, `app`,
`admin` and `www`. A school's subdomain is therefore valid for TLS **the moment
its tenant row exists** — there is no per-tenant certificate step to run, and
none to forget.

Served from `/etc/letsencrypt/live/nexchool.in/{fullchain,privkey}.pem`, which
is what `school-erp-infra/nginx/nginx.prod.conf` points at. Those paths do not
change on renewal, so nginx config needs no edit when the cert rotates.

**Wildcards are one level deep.** `bps.nexchool.in` is covered;
`a.b.nexchool.in` is **not**. If nested tenant hostnames are ever introduced,
this design must be revisited — it will not silently keep working.

---

## Why DNS-01, and why only one record moved

Let's Encrypt refuses to issue a wildcard over HTTP-01; wildcards require
DNS-01, which means certbot must write a TXT record into DNS unattended.

DNS for `nexchool.in` is at **Spaceship**, not Route53, and that zone also
carries things that have nothing to do with this app:

| Record | Points to | Service |
|---|---|---|
| `nexchool.in` A | `216.198.79.1` | Vercel (landing page) |
| `www` CNAME | `…vercel-dns-017.com` | Vercel |
| `docs` CNAME | `…vercel-dns-017.com` | Vercel (separate project) |
| `MX` ×2 | `mx1/mx2.spacemail.com` | Spaceship email |
| `TXT` | `v=spf1 include:spf.spacemail.com ~all` | email SPF |
| `*` A | `13.206.92.120` | EC2 — every tenant |

Migrating the whole zone to Route53 would have meant recreating **live email**
(MX + SPF + DKIM) on an inventory that cannot be fully enumerated from outside —
DKIM selectors are not discoverable by query, and getting them wrong fails
silently by sending mail to spam.

So the zone did not move. Only the challenge name is delegated:

```
_acme-challenge.nexchool.in   NS →  ns-1198.awsdns-21.org
                                    ns-1022.awsdns-63.net
                                    ns-366.awsdns-45.com
                                    ns-2033.awsdns-62.co.uk
```

Those are the delegation set of Route53 hosted zone
**`Z09350442V23LLB2DYNSF`** (`_acme-challenge.nexchool.in`), which contains
nothing but the TXT record certbot writes. Everything else in `nexchool.in`
still resolves from Spaceship and is untouched by certificate work.

Adding that NS set in Spaceship triggers an **"Add conflicting NS record?"**
warning. It is a false positive — the UI cannot distinguish "NS on a host that
has other record types" (genuinely unstable) from "a 4th nameserver added to an
NS set that already has 3" (normal delegation). The latter is what this is.

---

## Credentials: there are none

Certbot authenticates to Route53 with the **EC2 instance role**
`nexchool-ec2-ecr-role` — no API keys exist on the box for this. The inline
policy `nexchool-certbot-dns-route53` grants:

- `route53:ListHostedZones`, `route53:GetChange` on `*`
- `route53:ChangeResourceRecordSets` on **`Z09350442V23LLB2DYNSF` only**

It cannot modify any other zone, and there is no Route53 zone for
`nexchool.in` itself to modify.

---

## Renewal

Unattended, via the `certbot-renew.timer` systemd timer already on the box.

`/etc/letsencrypt/renewal-hooks/deploy/10-reload-nginx.sh` reloads the nginx
container after any successful renewal. **This hook is load-bearing.** nginx
reads certificates at start/reload and holds them in memory; without the hook
certbot renews on disk while nginx keeps serving the previous certificate until
something restarts it, which ends as an expired-certificate outage across
`api`, `panel` and every school at once. Do not remove it.

Verify renewal health without issuing anything:

```bash
certbot renew --dry-run
```

---

## Manual reissue (rarely needed)

```bash
certbot certonly --dns-route53 --cert-name nexchool.in \
  -d nexchool.in -d '*.nexchool.in'
```

Run via SSM (`send-command` runs as root already — see `production-access.md`).

---

## Verifying

The useful check is a subdomain that has **never existed**, because that is
what proves the next school will work. No tenant needs to be created:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://tenant-does-not-exist-yet.nexchool.in/
# 307 with TLS verified = any future school is already covered
```

Note the absence of `-k`. A check that passes only with `-k` proves nothing —
that flag disables exactly the validation a client's browser performs.

Inspect what is actually served:

```bash
echo | openssl s_client -connect bps.nexchool.in:443 -servername bps.nexchool.in 2>/dev/null \
  | openssl x509 -noout -subject -dates -ext subjectAltName
```

---

## What this replaced, and the failure to not repeat

Until 2026-09-15 the lineage was HTTP-01 (`authenticator = webroot`) with each
subdomain listed by hand: `api`, `panel`, `default`, `mts`. Two consequences,
both hit in production:

1. **Every new school shipped a browser security warning.** DNS (the `*` A
   record), the `*.nexchool.in` nginx server block and app routing all handled a
   new subdomain correctly on their own — only the certificate enumerated
   subdomains manually. Tenant creation was never wired to certificate issuance
   at all, so the gap was guaranteed for school #3 onward. It surfaced with
   `bps.nexchool.in`, where the first thing the client saw was "not secure",
   while `curl -k` returned a correct `307`.

2. **Every tenant was coupled to `api` and `panel`.** Certbot fails a lineage as
   a whole, so one subdomain with broken DNS — including a deleted tenant whose
   stale SAN was never pruned — would have failed renewal for the entire
   platform.

The general lesson: **a subdomain is not live because DNS and routing resolve.**
Three independent layers must agree — DNS, TLS, and the nginx server block — and
only the first two are visible to `curl -k`. Wildcards at all three layers is
what makes them agree by construction instead of by remembering.
