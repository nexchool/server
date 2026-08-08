# GraphQL conventions — what a migrating module follows

> The strategy is in `backend-architecture.md`: GraphQL is the primary business
> API, REST stays for infrastructure, one operation lives on exactly one
> transport, and replaced REST code is deleted. This document is the narrower
> thing — the conventions the Students pilot established, so the next module
> copies a decision rather than making it again.

Everything here is enforced by a test. Where a rule exists because something
went wrong, the reason is written down; a rule whose reason is lost gets
dropped by the next person who finds it inconvenient.

---

## 1. A module owns its GraphQL, the schema only composes

```
modules/<module>/
    resolvers.py         the fields, and nothing else
    graphql/
        types.py         what a client sees
        loaders.py       batched reads for one request
```

`graphql_api/schema.py` adds the module's `Query` / `Mutation` class to the
root. Nothing about a module's business lives in `graphql_api/`.

While a module has operations on both transports, they must run **one query
builder**. Students extracted `_student_list_query` for exactly this: a filter
added to one and not the other is drift nobody sees until a school asks why a
spreadsheet and a screen disagree.

Resolvers stay thin: they turn arguments into a service call and the answer
into a type. A resolver that queries the database directly is a service that
was not written — and it can then only ever be reached by GraphQL.

---

## 2. Every field declares what it requires

```python
permission_classes=[IsAuthenticated, RequiresTenant, requires("student.read.all")]
```

In that order: there is no authority to check before we know who is asking
and which school they are asking about.

Where a read is offered to more than one kind of person on different terms —
a head teacher reads the whole school, a class teacher only their classes —
use `requires_any(...)` and let the **resolver** decide what each one gets.
The guard answers "may this field run", never "how much of it".

`RequiresTenant` is not ceremony. This endpoint serves tenant-less operations
too — signing in happens before a tenant is known — so the transport resolves
tenant permissively. With no tenant in context **the ORM scope is inert**, and
a business field that runs anyway reads every school's rows.

Writes add the gates REST applies to writes:

```python
WRITES = [IsAuthenticated, RequiresTenant, SetupComplete, requires("student.update")]
```

`SetupComplete` only. The subscription gate REST carries is already covered
here: the transport refuses to resolve a tenant that is not active, so a
suspended school never reaches a field at all. Adding a second check for a
state that cannot arrive is machinery that will one day be believed.

An **optional** module adds one more, on reads as well as writes:

```python
requires_feature("attendance")
```

A school may not have bought the bus, may still take the register on paper.
It reads the same per-tenant switch REST does. Skip it for CORE features
(students, teachers, classes) — those cannot be switched off, so the gate
would never fire, and machinery that never fires is machinery that will one
day be believed.

Branch scope is **not** a transport concern. It belongs in the service, so it
holds however the workflow is reached — REST, GraphQL, or another service
calling it in a loop.

---

## 3. Paging walks by key

```graphql
students(first: 25, after: "QURNLTAwMDc=") { edges { cursor node { … } } pageInfo { hasNextPage endCursor } }
```

Not OFFSET. OFFSET makes the database count past everything it skips, so page
300 of a fifteen-thousand-student trust costs three hundred times page one —
and a child admitted while somebody pages shifts every later row, so a student
is seen twice or missed. Walking from the last key costs the same at any depth.

- Order by something unique, immutable and already meaningful to the school
  (students use the admission number).
- Cursors are **opaque** (base64) so a client cannot construct one and page
  from somewhere the server did not offer.
- Ask the service for `first + 1` rows. That extra row *is* `hasNextPage`,
  with no second query.
- Cap the page size in the **service**, not the resolver. A cap a caller can
  route around is not a cap.
- Offer `offset` **only** where a page-number control has to jump, which a
  cursor cannot express. It is a known cost the caller chooses, not a default,
  and asking for both `after` and `offset` is refused rather than resolved.
- A cursor is only sound over a key that cannot be null and does not change.
  Offer one for those orders and refuse it for the rest — over a nullable,
  mutable key a cursor does not error, it loses students.
- When a sort has a tie-breaker, the cursor carries **both** values, and a
  descending sort with an ascending tie-breaker is not a row comparison: it is
  "an earlier key, OR the same key and a later tie-breaker". Test it with two
  rows that share a key, or nothing will notice.

`totalCount` is a resolver on the connection, not a field computed with the
page: a list that shows no total should not pay for one.

**Where no key qualifies, offer offset and no cursor.** Classes have no such
key — every order the list offers is nullable (a class may have no grade),
mutable (grade order, a label) or a count that changes as children are
admitted. So `classes` returns a `ClassPage` of `nodes`, with `hasNextPage`
and `totalCount` and no cursor anywhere. Shipping an `endCursor` that is
always null would be machinery that never fires, and machinery that never
fires is machinery somebody will one day believe.

That is affordable because the *thing* is bounded, not because paging is
cheap: a school's classes are its own structure — twenty campuses of forty
sections is eight hundred rows — while its children are fifteen thousand.
Check which of those a list is before copying either shape.

---

## 4. Batching is synchronous here

**Do not reach for Strawberry's `DataLoader`.** It is async, and this
application is synchronous — WSGI, sync SQLAlchemy. It fails outright with
*"There is no current event loop in thread 'MainThread'"*.

The synchronous equivalent: the resolver that produced a page **primes** every
key that page will be asked about, in one query, and the per-object field is a
dictionary lookup.

```python
info.context.loaders.classes.prime(row.class_id for row in rows)
```

Loaders are built per request in `graphql_api/context.py`. Two requests must
never share one — the cache holds one tenant's rows.

Misses are cached too, so a missing parent is not looked up once per child
pointing at it.

---

## 5. A refusal says which kind it is

Services answer with `{"success": False, "code": …, "error": …}`. The message
is for a person; the code is for the transport.

```python
_REFUSALS = {"NOT_FOUND": NotFoundError, "WRONG_YEAR": ValidationError, …}
```

Never infer the kind from the message. A transport that recognised
*"already recorded as withdrawn"* by matching the sentence keeps working until
somebody rewords it, and then quietly reports a conflict as an unexpected
error. Anything without a code is a state conflict.

Refusals raised as exceptions deep in a service — `BranchForbidden` and its
kin — are translated once, in `TranslateDomainRefusals`. REST turns those into
status codes with a Flask error handler, which never runs inside a resolver:
untranslated, the client is told an unexpected error occurred and we log our
own bug. A module migrating should not have to remember this.

---

## 6. The type is what a client renders, not what a table holds

The REST payloads grew to carry every column any screen ever wanted, and every
caller pays for all of them. A GraphQL type starts with what the thing *is*
and gains fields when something actually renders them.

Use real scalars — a date is `datetime.date`, not an ISO string — so the
schema states the contract instead of describing it in a comment.

**A label a screen has to compose is a field the schema should have.**
`Class.displayName` and `StudentClass.displayName` exist because `classes.name`
is a nullable legacy label, empty for every class the structured form creates.
Five screens composed their own from it and five screens were wrong — a page
titled "— A", a filter offering twelve options all reading "-A", a picker of
blank checkboxes. Where a client must combine columns to get a name, put the
combining here; there is one of it, and it can be tested.

**Say the word the rest of the schema says.** The canon calls a class a
Section, and `Campus` was named after the canon rather than after the
`school_units` table it reads. `Class` is not, because the schema was already
full of the word — `Student.currentClass`, the student filter's `classId`,
attendance — and one concept under two names *on one transport* is worse than
one concept under the older name. Rename when the whole surface can move
(ADR-012 is the bridge), not one type at a time.

Name mutations as the school names the act: `withdrawStudent`,
`graduateStudent`, `transferStudentOut`. Not `updateStudentStatus`. A mutation
named after the column puts the school's history back in the hands of whoever
remembers to write the rest of it.

---

## 7. One field, one authority

Do not bundle several reads behind one field to save a round-trip. The
academic structure — campuses, years, programmes, grades, mediums — answers to
five different permissions, and today a person holding four of them sees four
lists rather than a blank screen. Behind one guard that becomes all-or-nothing;
behind one field, a single refusal fails the whole response.

A client still asks for several fields in one request and still pays for one
round-trip. The saving belongs to the transport; the authorities stay separate
because they *are* separate.

Bundle only where the data genuinely shares one authority and one lifetime.

**Read the route's decorator; do not infer the key from the module name.** Two
of the first five academic fields were guarded wrongly by guessing: mediums
also answer to `class_subject.manage` (a class-subject is taught in a medium),
and academic years answer to *nothing* — which year it is is ambient context a
student needs as much as an administrator. Both would have taken a working
screen away from somebody, and neither showed up in a test written from the
same guess.

---

## 8. Migrating a route

1. Build the GraphQL field beside the REST route. Both exist only while the
   client moves — the debt register carries that as an open item, because a
   business operation on two transports is exactly what the strategy forbids.
2. Move the client.
3. **Delete the REST route.** Not deprecate. The canon's rule is that dead
   code does not remain in the product, and a route nobody calls is the one
   nobody re-checks when the rules change.
