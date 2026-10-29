---
title: Election results
description: Running and administering live and archived election results.
aiAssistedGeneration: true
---

## Overview

A results version is read one of two ways, and each has exactly one source of
tallies. Both produce identical JSON, so components never know which delivered
a tally; only a status indicator does.

| Mode | Tallies from | Everything else from | Server rendered |
|---|---|---|---|
| **Live** | Firestore, written by the results worker | R2: the manifest and persistent data, both published beforehand | No |
| **Archived** | R2, published by Django | R2 | Yes |

**Django is not in the request path on election night.** It publishes the
manifest, the persistent data and the Firestore event document before polls
close; after that, nothing it runs is required for the dashboard to work. That
is the whole point of the arrangement: on the one evening that cannot fail, the
number of things that have to be alive is as small as it can be made — Firestore
and a static bucket.

The Django API is **not a client read path in production** either. The Django
instance runs on a VM with limited resources, so the client reads static JSON
from R2. Django remains the source of truth and generates that JSON. Pointing a
development client at a local Django instance exercises the same shape, because
the snapshots are rendered by the same serializers.

### Who owns what

Nothing has two owners. Writing to something you do not own will be overwritten.

- **The results worker** (`election-results-manager`) owns the Electoral
  Commission's data in Firestore: the `results` documents, the `election_*`
  reference collections, and the `refdata_built` flag on the event document.
- **Django owns the `persistent_*_id` fields on those `election_*` documents**,
  and only those fields. They say which cross-election record a row belongs to.
  The worker fills them in for the rows it recognises; the rest are decided here
  by `match_persistent_entities` and pushed back by `push_election_links`. Every
  write on either side is a merge, so neither disturbs the other's fields — but
  see the warning under that command.
- **Django** owns the event's own description (names, dates, embargo, bloc
  ordering, incumbency) and the persistent entities that survive across
  elections — party colours, and the links from candidates to people on the
  site. It pushes both into Firestore.
- **Django** owns `paths` on the event document, the same map it publishes into
  the manifest, written on every publish. The worker owns `refdata_built` on
  that same document; both writes are merges, so neither disturbs the other.
- **The feed worker** (`election-feed-worker`) owns the `feed` collection,
  except for the service announcements Django posts into it. It reads the
  results and the reference data and writes nowhere else. See
  [The feed](#the-feed).
- **Django** owns everything on R2.

## Identity

Two identifier spaces, and mixing them up is the most common source of confusion.

**Election-scoped entities — electorates, parties, candidates, voting places —
are referenced by their Electoral Commission `number`.** These are the
Commission's own integers, and they are what live Firestore results carry. They
are consistent within one election but **may be reused between elections**, so a
number means nothing without a results version beside it. Every cache key,
index and lookup in the client is scoped to one.

**Persistent entities are referenced by their Django UUID**, because they exist
precisely to survive across elections and so cannot be keyed on a number that
does not.

**Persistent entities use the same id in Firestore as in Django.** The
persistent collections are keyed by the Django UUID, and `persistent_*_id` on
the worker's `election_*` documents carries that UUID directly, so there is one
identity space rather than two to translate between.

That was not always true. These documents used to be keyed by Mongo ObjectIds
inherited from an earlier implementation, and electorates by their `legacy_id`
integer. `align_firebase_ids` moved them; `legacy_id` is still carried as a
field, because it is the Commission's own cross-election number and worth
keeping, but nothing resolves by it. The client still accepts either form, so a
document that has not caught up resolves anyway.

Firestore ids for the `results` documents remain ObjectIds. They are stable per
results set, which is what makes the worker's writes idempotent. Results are
identified by what they are rather than where they are stored — with one
exception, below.

### Why a results set carries its Firestore id

A results set is identified by its canonical key:
`level:category:electorate:voting_place:discriminator`. The first four
components are what the tally *is*, and they agree across every transport,
which is what lets a live update replace the published figure it supersedes.

The last component exists because those four are not always enough. The
Commission has published advance votes and polling-day votes as **separate sets
for the same voting place**, and may do so again; which way it goes is not known
in advance. `ResultsSet.result_number` is the field meant to say which set it
is, and **nothing populates it** — it was renamed from `voting_place_number` in
migration `0024` and the Firestore importer never writes it, because no field in
the feed has been confirmed to carry the ordinal. `voting_place_no` is the
likely candidate (a voting place document in `migration/example_results.json`
carries `voting_place_id: 4206` alongside `voting_place_no: 1`, which are
plainly different things), but that is a reading, not a verified fact, and
filing a tally under the wrong voting place is worse than the problem it solves.

So until the ordinal is confirmed, the discriminator is the **Firestore document
id**: it is the one value a published set and its live twin both hold, since
`ResultsSet.firebase_id` *is* that id. `ResultsSetSerializer` puts it on the
wire for that reason alone.

Without a discriminator both sets collapse onto one key, and the client holds
one entry per key and keeps whichever tally carries the later timestamp. The
place then reads low by exactly the set that was dropped, with nothing on screen
to say so. `publish_election_snapshots --voting-places` reports any remaining
collision before publishing, so the condition is found rather than inferred
later from a total that looks slightly off.

Pages aggregate over sets rather than picking one, so a place that reports twice
reads as one figure either way.

## Data model

### Election

| Field | Purpose |
|---|---|
| `polling_date`, `polls_close` | `polls_close` drives the countdown gate on the dashboard |
| `voting_period_start`, `voting_period_end` | Advance voting dates |
| `election_type` | `general` or `by-election`. Pushed to Firestore as `by_election` |

### ElectionResultVersion

An election can have several results versions — election night, preliminary,
final. Each is a separate set of results over the same election.

| Field | Purpose |
|---|---|
| `is_primary` | The version served when the URL says `default` |
| `access_mode` | `api` or `firebase`. Necessary for live mode but **not sufficient** |
| `firebase_id` | The Firestore event id, eg `ge2023_e9` |
| **`is_live`** | **The switch that puts clients on Firestore.** See below |
| `is_final` | Counting is complete; the dashboard says "Final results" |
| `refdata_built` | Read back from Firestore. The worker owns it; Django never writes it |
| `embargo_start`, `embargo_end` | The worker must not write results before `embargo_end` |
| `result_targets` | `[{"proportion": 0.5, "target_time": "..."}]` |
| `comparison_version_ids` | Ordered UUIDs of versions to compare against |
| `bloc_order_left`, `bloc_order_right` | Ordered `PersistentParty` UUIDs. See [Blocs](#blocs) |
| `card_image` | Social card image, uploaded here. Published in the manifest as `card_image_url` |
| `snapshot_paths` | Where this version's payloads were last published |
| `last_firebase_push_at`, `last_snapshot_published_at` | Audit |

The three ordered lists are `JSONField`s rather than many-to-many relations,
because ordering is the whole point of them and a relation would lose it. That
trades away referential integrity, so `clean()` validates that the referenced
rows exist. They are resolved to Firestore ids when pushed.

`incumbents` used to be a fourth `JSONField` here. It is now two tables, below:
an incumbent is a row with real foreign keys, which is what lets the manifest
carry ids the client can resolve.

### `is_live` is one field with two jobs

There is a single `is_live` on `ElectionResultVersion`. Saving it propagates to
two places, which do different things.

| Copy | Reached by | Decides |
|---|---|---|
| **`manifest.json`** | queued manifest rewrite, ~30s cache | Which transport a page loads with. `is_live` **and** `firebase_id` means Firestore; anything else means the published snapshots |
| **Firestore `events/{id}`** | `post_save` signal, near instant | Whether a count already being watched is still live |

The manifest decides on its own, before any Firestore connection is opened.
That matters: it is static, edge cached and readable on the server, so a client
never waits on a network round trip to learn which path it is on.

The event document's copy is **the kill switch**. Turning `is_live` off in the
admin cancels the results listeners on every open page, tells the reader so —
the status badge changes to "Live updates ended" — and drops them back to the
published snapshot without a reload. New visitors follow about thirty seconds
later, once the manifest has caught up.

The event-document listener stays attached after a count ends, so turning the
switch back on recovers open pages rather than stranding them.

**Rehearse this before an event.** And read "To end the count" below first: the
order matters, because the published snapshot is what open pages land on.

`access_mode` is no longer part of the decision. `firebase_migrate_events` sets
it to `firebase` for every *archived* event it imports — both ge2020 and ge2023
carry it despite living entirely in MySQL — so it never could decide anything.
It stays on the model because the Firestore push signal still gates on it.

## Incumbency

Who held what going into an election. Without it the dashboard can say who won
a seat but not whether that is a change, so no flip can be shown and no party's
total can be read as a gain or a loss.

Two tables, both scoped to a results version, because a duplicate version of
the same count is still the same set of sitting members and should be able to
disagree if it has to.

### `ElectorateIncumbent`

One row per electorate held.

| Field | Purpose |
|---|---|
| `electorate` | The persistent `Electorate`. There is no `PersistentElectorate`: an electorate already survives across elections |
| `persistent_candidate` | The sitting member. Null where the seat was vacant going in |
| `persistent_party` | The party the seat was **won** for. This is what a flip is measured against |
| `has_left_party` | The member no longer sits for that party |
| `current_persistent_party` | Where they sit now. Null with `has_left_party` set means an independent |
| `notes` | Free text, for anything a curator needs to record |

### `PartyIncumbent`

One row per party defending seats: `persistent_party`, `electorate_seats` and
`list_seats`.

These are the seats held **at dissolution**, counting where each member sits
now rather than the party they were elected for -- a member who crossed the
floor stopped counting towards their old party's total the day they did it.
That is the figure a reader compares a result against, and it is the one thing
about these numbers that is easy to get wrong. List seats cannot be derived
from anything this database holds, which is why both counts are curated;
`copy_incumbents` reports where `electorate_seats` disagrees with the
`ElectorateIncumbent` rows.

### Only defections are curated

The client has to tell three cases apart, and only the last needs a field here:

| Case | Decided by |
|---|---|
| The member is standing again for the party that won the seat | Derived |
| The party is standing somebody else -- the small cross marker | Derived |
| The member is standing for another party, or as an independent | Derived |
| The member left their party and is **not** standing again | **Curated** |

The first three are worked out in the client's `useIncumbency` by matching
these persistent records against the version's own candidate list, which
already carries `persistent_candidate` and `persistent_party` on every row.
Deriving them is what keeps them honest: the candidate list is authoritative,
so a marker on a seat cannot contradict the names printed beside it. Only a
member who crossed the floor and is then not standing leaves nothing in that
list to infer from, which is why `has_left_party` exists.

Anything not fully linked reads as unknown in the client and shows no marker,
rather than a confident one that is wrong.

## Blocs

Parties were ordered by size everywhere seats are drawn, which is the one
arrangement that cannot answer the question a chamber is for: who could govern
together. `bloc_order_left` and `bloc_order_right` are ordered
`PersistentParty` UUIDs, curated per results version because an alignment
changes between elections.

One rule decides the whole seating plan:

```
[*bloc_order_left, *cross-bench, *bloc_order_right]
```

reads from the far left of the chamber to the far right. So the left list is
curated **far-left first** and the right list **centre first**. A party in
neither list is cross-bench, sits in the middle, and is ordered by size.
`clean()` rejects a party in both lists, since it could not be seated twice.

Seats belonging to nobody -- an unfilled list seat, or an electorate still tied
-- also sit in the middle. Appending them would pad whichever bloc is on that
edge and make it read as larger than the count supports.

Where neither list is curated the client falls back to ordering by size, so
every archived election is drawn exactly as it was before.

These were called `coalition_order_*`. Before an election there is no
agreement, only an alignment, so they are blocs.

## What propagates automatically

Clients never read this database. They read the published manifest and, during
an event, Firestore. So a change made in the admin has no effect on anyone until
it reaches one of those.

Three things travel on their own, all small and singular:

| Saved | Propagates | Why automatically |
|---|---|---|
| `ElectionResultVersion` | The Firestore `events` document | One row per event, and it carries the embargo and bloc ordering the worker reads |
| `Election` or `ElectionResultVersion` | `manifest.json` | It carries `is_live`, `is_final` and the version's name. Leaving it manual would make the kill switch inert |
| `ElectionVotingPlace` | The `ElectionVotingPlaces` Algolia index | One row is one record, so a corrected address is one API call |

The first two are queued on `transaction.on_commit` so a save never waits on a
network round trip, and a broker that is down is logged rather than failing the
save.

The voting place record is the exception: `algoliasearch-django` writes it from
the `post_save` receiver, in whatever process did the save, so an admin edit
does wait on Algolia. Set `ALGOLIA_AUTO_INDEXING=False` to turn that off for a
process that saves them one at a time in a loop, and sync the index afterwards.
It defaults to off under the test runner, which otherwise writes to a real
index.

Rewriting the manifest regenerates **nothing**: it is a few kilobytes, rebuilt
from the paths each version was last published at.

Deliberately **not** automatic:

- **Snapshot payloads.** Reference, results and persistent data run to over a
  megabyte and change when the data changes, not when a description is edited.
  Use the admin action or `publish_election_snapshots`.
- **Persistent entities in Firestore.** Re-importing a few thousand candidates
  would enqueue a few thousand tasks. Use the admin action or
  `push_persistent_to_firebase`.
- **Voting places arriving by import.** The row-level propagation above rides
  on `post_save`, and `firebase_migrate_elections` writes them with
  `bulk_create` and `bulk_update`, neither of which sends one. So an import
  reaches Algolia only through a sync. `sync_reference_data` queues one for the
  version it just imported, which covers `sync_live_elections`; running
  `firebase_migrate_elections` directly does not, so follow it with
  `sync_voting_places`.

A results version that has never been published has no recorded paths, so it
stays out of the manifest until it is published properly for the first time.

## Snapshots on R2

### Layout and caching

```
manifest.json                                          max-age=30, swr=300
persistent-{hash}.json                                 immutable
events/{election}/{version}/reference-{hash}.json      immutable
events/{election}/{version}/results-{hash}.json        immutable
events/{election}/{version}/voting-places/by-electorate/{n}.json   max-age=60
events/{election}/{version}/voting-places/by-place/{n}.json        max-age=60
```

The two voting place shardings answer opposite questions and neither replaces
the other. `by-electorate/{n}.json` is every place within electorate *n*.
`by-place/{n}.json` is every electorate that voting place *n* issued votes for,
which is what the page for a single place reads: a place serves several
electorates, so its own tallies are scattered across those electorates' shards
and assembling one place from them would mean fetching all of them. The
per-place files are the bulk of a `--voting-places` publish, one small object
per place. A place with nothing counted has no file at all, and the client reads
that absence as "nothing reported here".

**Filenames carry a content hash** — the first twelve characters of the SHA-256
of the file itself. Clients never construct these names; they read
`manifest.json`, the only URL the client hard-codes, and follow the paths it
gives. Hashing means the large payloads can be cached forever and never
revalidate, and that republishing unchanged data is a no-op.

`manifest.json` is the single mutable pointer, which is why it is written
**last**: until it names a path, nothing is visible, so a publish that fails
part way leaves the previous state intact.

### What rides in the manifest rather than a payload

The manifest carries the event's **curated description** as well as the paths:
`is_live`, `is_final`, `card_image_url`, and the two things below. Those are
edited by a person rather than produced by a count, so they ride here and reach
a client on the save, through the queued manifest rewrite, with nothing to
publish.

```json
"blocs": { "left": ["<uuid>", "..."], "right": ["<uuid>", "..."] },
"incumbency": {
  "electorates": [
    { "electorate": "<uuid>", "candidate": "<uuid>", "party": "<uuid>" },
    { "electorate": "<uuid>", "candidate": "<uuid>", "party": "<uuid>",
      "left_party": true, "current_party": "<uuid>" }
  ],
  "parties": [
    { "party": "<uuid>", "electorate_seats": 23, "list_seats": 11 }
  ]
}
```

**Persistent ids and nothing else.** The client already holds every persistent
object from `persistent-{hash}.json`, so the manifest names them rather than
repeating them.

Two rules keep the one object every visitor fetches small, and both are tested.
Null and false members are **left out** rather than written, so an absent
`candidate` is a seat with no sitting member and an absent `left_party` is a
member still with their party. And the whole `blocs` or `incumbency` key is
omitted where nothing has been curated, so an archived election costs nothing.

A fully curated general election — 72 electorates and 20 parties — measures
about **13 KB, or 6 KB gzipped**, which is what the edge serves. Three UUIDs a
row is most of it. Only the current election is normally curated, so that is
roughly what the manifest grows by in total rather than per version. It is
worth knowing the figure: the manifest is read on every server-rendered
election page and by every visitor within its thirty-second cache lifetime, so
if this ever had to carry a decade of elections it would belong in a
content-hashed payload named from `paths` instead.

Electorates are ordered alphabetically and parties by seats held, so the file
is readable and a diff between two publishes is meaningful.

Every results payload is content addressed, including during a count. There is
no rolling file with a stable name any more: live tallies come from Firestore,
so the only results object published is the immutable one a client falls back
to once the count ends. Publishing one therefore always rewrites the manifest,
which is what makes the new path reachable at all.

Persistent data is published at the bucket root rather than per event. Content
addressing means identical data lands on one object that every event shares.

The social card image is the one payload that does not live in this bucket. It
is uploaded to the version in Django admin, stored in public media alongside
every other uploaded file, and the manifest carries its resolved URL as
`card_image_url` — null where no card has been uploaded. The URL is unsigned,
because a crawler may fetch it long after the manifest was written.

### Boundaries ride with the electorate

Each persistent electorate in `persistent-{hash}.json` carries a `boundaries`
list: every boundary set the electorate has had, **newest `valid_from` first**.

```json
{
  "id": "<uuid>", "name": "Ilam", "slug": "ilam", "region": "Canterbury",
  "electorate_type": "general", "status": "current", "legacy_id": 17,
  "boundaries": [
    {
      "id": "<uuid>",
      "boundary_set": "<uuid>",
      "valid_from": "2026-01-01",
      "shape": {
        "id": "<uuid>",
        "url": "https://media.wheretheystand.nz/.../ilam-2026.geojson",
        "copyright_owner": "Land Information New Zealand",
        "licence": "CC BY 4.0",
        "licence_grantor": "Stats NZ"
      },
      "simplified_shape": { "...": "as above, fewer vertices" }
    }
  ]
}
```

An electorate persists across elections; its lines do not. So the set's
`valid_from` is lifted onto each boundary, and choosing between them is the
client's: the head of the list for a current map, or the newest set in force on
polling day for a past election. Carrying it here means no page has to hold the
boundary sets as a collection of their own, and none has to call Django for a
map — which is the point, because on the night Django is not in the request
path. The ordering is part of the contract and is tested.

**Only the URL travels.** The GeoJSON itself stays in public media and is
fetched for the one boundary a page draws; `simplified_shape` is the one to
prefer and is null where a set has none. The three attribution fields are flat
names rather than the API's nested copyright objects, because a map drawn from
a published shape has to credit it and the credit cannot be a second request.
Everything else on the file record is left out: this payload is inlined into
every server-rendered election page.

**Both copies carry it.** The `persistent_electorates` documents in Firestore
hold the same `boundaries` list, field for field, nested on the electorate
rather than given a collection of its own -- a collection would be another
per-visitor read on the pages that draw a map, and reference data already
dominates the Firestore bill. Keeping the two identical is tested: published
reference data is what a client reads once it exists, and Firestore is what it
reads until then, so a map that only appeared after publishing would be a gap
nobody notices until a night when publishing has not happened yet. It is also
why `valid_from` is an ISO date string in Firestore rather than a timestamp.

Boundaries change with a Representation Commission, not with a count, so
nothing propagates them automatically. After `upload_electorate_boundaries`,
run `publish_election_snapshots` (or the admin action) and
`push_persistent_to_firebase --only electorates`.

### Configuration

Three `STORAGES` aliases over one bucket, because django-storages sets object
parameters per storage rather than per save and these need different caching:
`elections_manifest`, `elections_snapshots`, and `elections_latest` for the
voting place files, which carry fixed names rather than content hashes.

| Variable | Default |
|---|---|
| `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Shared with other buckets |
| `ELECTIONS_BUCKET` | `elections` |
| `ELECTIONS_SNAPSHOT_DOMAIN` | `elections-r2.wheretheystand.nz` |

On the client, `NUXT_PUBLIC_ELECTIONS_SNAPSHOT_BASE` defaults to that domain.
`NUXT_PUBLIC_ELECTIONS_ENABLED` must be `"true"` for any `/elections` route to
resolve at all.

## Commands

### `publish_election_snapshots`

Renders the payloads and uploads them.

```bash
python manage.py publish_election_snapshots --dry-run
```

| Flag | Effect |
|---|---|
| `--dry-run` | Lists every object and its size. Writes nothing |
| `--local <dir>` | Writes the same tree to disk. Does not record paths as published |
| `--election-slug`, `--version-slug` | Narrow to one election or version |
| `--voting-places` | Also publish voting place data: the reference payload, the per-electorate shards and one file per voting place. Several thousand objects; slow. Reports canonical key collisions before writing |

Publishing one version still rewrites the manifest **in full**, using
`snapshot_paths` for versions not republished. Publishing one event cannot drop
the others from the manifest.

### `push_event_to_firebase`

Pushes a results version's `events` document — the description the worker and
the client both read.

```bash
python manage.py push_event_to_firebase --version-slug final --dry-run
```

`--all-live` pushes every version marked live. Always dry-run first: this is a
payload you get one chance at on the night.

### `push_persistent_to_firebase`

Pushes party colours, candidate-to-person links and the rest.

```bash
python manage.py push_persistent_to_firebase --only parties --dry-run
```

`--only` accepts `parties`, `candidates`, `electorates`, `voting-places`.

Every collection is keyed on the Django UUID, electorates included. Nothing is
skipped for want of an id, which was not the case while electorates were keyed
on `legacy_id`: one without it could not be pushed at all.

Electorate documents carry their `boundaries`, the same list the published
payload has — so a boundary import needs this command as well as a publish.
Only the shape URLs and the set's `valid_from` go in; the GeoJSON would not fit
in a document and a client draws one shape anyway.

### `push_election_links`

Writes this database's curated persistent links into the `election_*`
collections, so that reference data read from Firestore carries the same links
as reference data read from R2.

```bash
python manage.py push_election_links --version-slug final --dry-run
```

| Flag | Effect |
|---|---|
| `--dry-run` | Report what would be written. Writes nothing |
| `--only` | Comma separated subset of `candidates`, `parties`, `electorates`, `voting-places` |
| `--election-slug`, `--version-slug` | Narrow to one election or version |

Only one field per document is written, always merged. Rows are skipped with a
warning where there is nothing to write or nowhere to write it: an election row
with no `firebase_id` was created here rather than imported and has no Firestore
document, and a persistent record with no Firestore id has not been pushed yet
— run `push_persistent_to_firebase` first.

**Push after the worker has built reference data, not before.** These fields sit
on documents the worker creates. If it rebuilds that collection with replacing
writes, anything pushed beforehand goes with it. Building reference data happens
once, at the start of an event, so in practice this means: wait for
`refdata_built`, import, match, then push.

### `align_firebase_ids`

A one-off migration, kept because it is safe to re-run and explains itself.
Points every persistent entity's `firebase_id` at its own Django UUID, pushes
the persistent collections at those ids, and rewrites `persistent_*_id` on every
`election_*` document to match.

```bash
python manage.py align_firebase_ids --dry-run
```

| Flag | Effect |
|---|---|
| `--dry-run` | Report what would be re-keyed. Writes nothing |
| `--no-push` | Update this database only, pushing nothing |

Old documents are **left in place**, so nothing is destroyed before the new ids
have been shown to work. Publish afterwards, because the persistent payload on
R2 carries these ids too:

```bash
python manage.py publish_election_snapshots
```

Then check the dashboard still resolves candidates through to people, and only
then clear the leftovers.

### `prune_persistent_documents`

Deletes persistent documents whose id is not a current Django id — the
ObjectId-keyed leftovers from before the migration. It cannot remove a document
that is still canonical for an entity, because those ids are exactly the ones it
excludes.

```bash
python manage.py prune_persistent_documents --dry-run
```

Reports by default. `--apply` is required to delete anything, and deleting is
not reversible without a Firestore backup.

Read the collection size, not just the delete count. Halfway through the
migration every collection holds two documents per entity, so a healthy report
looks like this — the deletions equal the entity count, and so do the documents
that remain:

```
persistent_candidates: 1358 document(s)
    679 at a current Django id, of 679 entities
    679 to delete
```

It **refuses to delete anything** if any entity has no document at its Django
id, because in that case the old document is the only copy that exists and
removing it would take the entity out of Firestore altogether. Run
`align_firebase_ids` and try again.

### `sync_live_elections`

Imports results from Firestore into Django and publishes what it imported. It
is **not a loop**, and nothing about a live count depends on it — clients read
Firestore themselves. An evening where this never runs still shows a working
dashboard.

```bash
python manage.py sync_live_elections --dry-run
```

| Flag | Effect |
|---|---|
| `--dry-run` | Reads Firestore and reports what a pass would do. Writes nothing |
| `--no-publish` | Import from Firestore without publishing |
| `--include-not-live` | Also process versions not marked live, for catching up afterwards |

Run it deliberately, twice — see "Election night" below. Once when the worker
has built reference data, to get that data onto R2 and named on the event
document; and once immediately before turning `is_live` off, so the published
snapshot is current at the moment it becomes what open pages fall back to.

It exits non-zero if any version failed. One failing event never stops the
others.

### `sync_voting_places`

Pushes election voting places to the `ElectionVotingPlaces` Algolia index — a
separate index from `SiteSearch`, searched by address and by proximity, and
faceted so that a query can be confined to one results version.

```bash
python manage.py sync_voting_places --election-slug 2026-general --version-slug final
```

| Flag | Effect |
|---|---|
| `--election-slug`, `--version-slug` | Narrow to matching versions |
| `--all` | Every results version that has voting places, one sync each |
| `--reindex` | Rebuild the whole index through a temporary index, moved into place atomically. Use after changing the index definition |
| `--queue` | Hand the work to Celery and return |
| `--dry-run` | Report how many places would be synced. Reads neither Algolia nor the queue |

A per-version sync also removes the records the index holds for that version
that this database no longer has, so a voting place that was deleted or
renumbered does not linger in search results. `--reindex` does the same for
every version at once, and is the only form that clears records belonging to a
results version that has itself been deleted.

Only `ElectionVotingPlace` is indexed. A `PersistentVotingPlace` carries no
election, electorate or number, so it cannot answer "where do I vote in this
election"; it appears on each record as `persistent_voting_place`, which groups
one physical place across the elections it was used in.

Every record carries `results_version`, `election` and `event` (the Firestore
events document id, absent until the version has been pushed), all three as
`filterOnly` facets. **A query must filter on a results version**, or the same
address comes back once per election it was used in.

Safe to run at any point in a count: the index is reference data, not results.

### Importing from Firestore directly

`firebase_migrate_events`, `firebase_migrate_persistent`,
`firebase_migrate_elections` and `firebase_migrate_results` import from
Firestore into Django. Each defaults to inspect-only and needs
`--migrate --event-id <id>`. `sync_live_elections` calls the last two for you.

## Matching persistent records

Persistent records are what let the site follow the same person or party across
elections. The Commission does not supply them, and the results worker only
matches what it recognises, so the rest is curated here.

```bash
python manage.py match_persistent_entities --election-slug 2023-general-election
```

Every unmatched row is classified into one of four outcomes:

| Outcome | Meaning | Acted on by |
|---|---|---|
| exact | Identical name, or identical party abbreviation | `--apply` |
| structural | Differs only by trailing given names | `--apply` |
| review | Something similar exists | never automatic |
| create | Nothing plausible | `--create-missing` |

The usual sequence is look, `--apply`, `--interactive`, `--create-missing`.

**Similarity scores never decide a link.** They decide only whether a row
reaches the review queue, because a false pair can outscore a true one — in the
2023 data `JOHNSTON, Brian ~ JOHNSON, Ian` scores 0.889 while the genuine
`GREENSLADE, David ~ GREENSLADE, David John` scores 0.865. No threshold
separates them, so linking is decided by structure instead: same surname, and
one list of given names is a prefix of the other. `--min-score` moves only the
boundary between "needs a decision" and "no plausible match".

`--interactive` works the review queue one row at a time, showing the party and
electorate you need to judge it: `[l]` link, `[c]` create, `[s]` skip, `[o]`
print the admin link, `[q]` stop.

Voting places are matched on proximity rather than address text, because the
Commission republishes coordinates for the same hall and they drift. The
threshold is 50 metres, matching the results worker; change it with
`--distance-metres`.

**Electorates are never created automatically.** They carry boundaries, a
region, a slug and validity dates that a results feed cannot supply, so the
command reports them and leaves creation to the admin.

Matching decides links that exist nowhere else, so all three of these afterwards:

```bash
python manage.py push_persistent_to_firebase                     # the records
python manage.py push_election_links --election-slug 2023-general-election
python manage.py publish_election_snapshots --election-slug 2023-general-election
```

The middle one is easy to forget and the failure it causes is quiet. Reference
data published to R2 carries Django's own foreign keys, so it always reflects
what you curated. Firestore's copy carries only what the worker matched, which
on the 2023 data was well under half — and until reference data is published,
Firestore is where every client gets it. A candidate whose link is missing
still shows the right name and the right tally; what disappears is the link
through to their profile on the site.

### Copying links between versions

A duplicate results version arrives with every persistent link empty, and the
reference data almost never changed: the same candidates stand in the same
electorates for the same parties, numbered the same way. So move the curation
across rather than deciding it again.

```bash
python manage.py copy_persistent_links --from final --to final-revised
python manage.py copy_persistent_links --from final --to final-revised --apply
```

Both versions must belong to the same election. Rows are paired by Electoral
Commission `number` — that is what the numbering is for — and then **checked**
before anything is written. Names must agree, allowing for middle names coming
and going, or a party's abbreviation must agree where its registered name was
edited; voting places must sit within 50 metres, matching how they are matched
in the first place. A pair that shares a number but disagrees about what it is
means the two versions are not numbered alike, so it is reported and left alone.

| Flag | Effect |
|---|---|
| `--apply` | Write the links. Without it, nothing changes |
| `--only` | Comma separated subset of `candidates`, `parties`, `electorates`, `voting-places` |
| `--election-slug` | Only needed when the version slugs are not unique across elections |
| `--overwrite` | Also replace links the target already has. Off by default: the existing link may be the curated one |
| `--allow-mismatch` | Copy despite a name disagreement, trusting the numbers. Look at the report first |
| `--distance-metres` | How far two voting places with one number may sit apart. Default 50 |

What it copies is `persistent_candidate`, `persistent_party`, `electorate` and
`persistent_voting_place`, and nothing else. Run `match_persistent_entities` on
the target afterwards for anything genuinely new, then push and publish as
above — the target version's reference data has changed.

### Copying incumbency between versions

The same problem as copying links, and a simpler answer. Incumbency is curated
by hand -- seventy-two seats and a row per party -- and a duplicate version
arrives with none of it, even though the answer has not changed: the same
members held the same seats whichever version of the count you are reading.

```bash
python manage.py copy_incumbents --from final --to final-revised
python manage.py copy_incumbents --from final --to final-revised --apply
```

There is no pairing and no identity check, because these rows point only at
persistent records and a persistent id means the same thing in both versions.
A row either is not in the target yet, is already the same, or disagrees.

| Flag | Effect |
|---|---|
| `--apply` | Write the rows. Without it, nothing changes |
| `--only` | Comma separated subset of `electorates`, `parties` |
| `--election-slug` | Only needed when the version slugs are not unique across elections |
| `--overwrite` | Also replace target rows that disagree with the source. Off by default: the row already there may be the curated one |

Both versions must belong to the same election, and that guard is the point
rather than a limitation. A version's incumbents are the winners of the
*previous* election, so copying across elections would produce a complete set
of rows that are quietly one election out of date — the kind of mistake that
looks right. Curate the first version of a new election by hand.

It also reports, without changing anything, where a party's curated
`electorate_seats` disagrees with the `ElectorateIncumbent` rows attributable
to it. A seat vacated mid-term is held by nobody, so the two can legitimately
differ; it is a prompt to look, not an error.

Incumbency rides in the manifest, so only the manifest has to be rewritten
afterwards — there is no payload to regenerate:

```bash
python manage.py publish_election_snapshots --election-slug <slug>
```

## Setting up a new election

1. **Create the `Election`** in Django admin: name, polling date, `polls_close`,
   and the advance voting period.
2. **Create an `ElectionResultVersion`.** Set `is_primary`, set `access_mode` to
   `firebase`, and set `firebase_id` to the event id the worker will use. Leave
   `is_live` **off**.
3. **Fill in the curated fields**: `embargo_start` and `embargo_end`,
   `result_targets`, `bloc_order_left` and `bloc_order_right`, and
   `comparison_version_ids`.
   Then **curate the incumbency**: an `ElectorateIncumbent` per seat held and a
   `PartyIncumbent` per party defending one. Party incumbents are edited inline
   on the version; electorate incumbents have their own changelist, filtered by
   version. For a second version of the same election, use `copy_incumbents`
   rather than entering them again.
4. **Push the event document**, dry run first:
   ```bash
   python manage.py push_event_to_firebase --version-slug <slug> --dry-run
   ```
5. **Push the persistent entities**, so party colours and person links exist
   before results start arriving.
6. **Publish snapshots**, so the manifest knows about the event:
   ```bash
   python manage.py publish_election_snapshots --election-slug <slug>
   ```
7. **Check the dashboard loads** and shows "Archived results" with no results
   yet. It should not error.

## Election night

### Before polls close

- Confirm `firestore.rules` and `firestore.indexes.json` are deployed:
  ```bash
  firebase deploy --only firestore:rules,firestore:indexes
  ```
  Do this well beforehand. An index built for the first time under load takes
  minutes you will not have.
- Confirm a **daily spend cap and budget alert** on the Firestore project.
  Security rules cannot rate-limit reads, so this is the only ceiling.
- Confirm the worker will not write before `embargo_end`. The embargo is not
  expressible in security rules without a billed document read per evaluation,
  so it is enforced at the writer.
- Check the **published manifest**, not the database: it must carry the right
  `firebase_id` and `polls_close` for the version, and `is_live: false` until
  you mean it. The client reads the manifest and nothing else to decide which
  transport it is on.
- Check `sync_live_elections --dry-run` reaches Firestore and reports the event.

### At polls close

1. **Set `is_live`** on the results version. Clients pick it up within about
   thirty seconds, and there is nothing else to start.

That is the whole step. There is no loop to launch, no broker to check, and no
cron entry that has to survive the evening.

### During the event

Nothing is required. Clients read tallies from Firestore and take the names
those tallies refer to from wherever the event document points them.

One thing is worth doing, once, when the worker sets `refdata_built`:

```bash
python manage.py sync_live_elections
```

This imports reference data, publishes it to R2, and names it on the event
document so that clients read it from the edge instead of pulling several
hundred documents out of Firestore each. It is a **cost saving, not a
requirement** — if the Firestore write fails the manifest still names the same
payload, and if nothing is published at all every client reads reference data
from Firestore and the dashboard renders exactly the same.

If any persistent links were curated here rather than matched by the worker,
push them back in the same pass, before clients read reference data from
Firestore:

```bash
python manage.py push_election_links --election-slug <slug>
```

Watch for: `refdata_built` staying false (the worker has not built reference
data), and the Firestore usage graph.

### What a visitor sees before the first results

The dashboard distinguishes several waiting states, so that an event which has
not started counting does not look broken. Each is a phase of one gate, and the
dashboard renders only when every condition below it has been met.

| State | Shown when |
|---|---|
| Countdown to polls close | The version is not final and `polls_close` is in the future |
| "The Electoral Commission has not published candidate and party details yet" | Live, `refdata_built` false |
| "Counting has begun" | Live, reference data loaded, no national tally yet |
| The dashboard | Polls closed, persistent data, reference data and a national tally all present |
| "No results available" | Archived, and nothing was published |

The waiting states carry a pulsing indicator, the live connection state and a
moving progress bar, so it is visibly working rather than stalled. The last has
none of that, because nothing is going to change.

### Where reference data comes from

Two places name the published payload, and both are tried before Firestore is:

1. **`paths.reference` on the event document** — preferred, because it arrives
   on the listener the page already holds, so a republish mid-count reaches a
   page that is already open.
2. **`paths.reference` in the manifest** — the same map as it stood when the
   page loaded. The manifest is edge cached, so it can be up to its cache
   lifetime behind, but it is read before any Firestore connection is opened and
   needs nothing to have been written on the night.
3. **The `election_*` collections in Firestore** — the last resort. Around 700
   documents for a general election, per visitor.

Django writes the same map to both places, so the first two normally agree and
the second fetch never happens. Publishing reference data is what changes the
answer; the cascade exists so that one stale or missing pointer costs a page
nothing but a second request.

### To end the count

**The order matters.** Open pages fall back to the published snapshot when the
switch goes off, so publish before you flip it:

```bash
python manage.py sync_live_elections     # import and publish current results
```

Then turn `is_live` off. Listeners are cancelled, the badge reads "Live updates
ended", and pages drop onto a snapshot that is current rather than onto
whatever was published before polls closed.

In a genuine emergency, flip the switch first and publish afterwards — an empty
archive for a minute is better than a feed you have decided is wrong.

### Afterwards

1. **Catch up the final import**:
   ```bash
   python manage.py sync_live_elections --include-not-live --version-slug <slug>
   ```
2. **Set `is_final`** once counting is complete. This is also what keeps the
   archived version from ever opening a Firestore connection again.
3. **Publish the full archive**, including voting places:
   ```bash
   python manage.py publish_election_snapshots --election-slug <slug> --voting-places
   ```

## The feed

The running commentary beside the dashboard: a lead changing hands, a voting
place reporting, the projected composition of Parliament moving, and the
occasional announcement from the site itself.

It is one Firestore collection, `feed`, with one document per entry. Readers
listen to the latest 20 for their event, newest first.

### What writes it

`election-feed-worker`, a Node container on Coolify, writes everything except
the announcements. It watches every results document for the live events,
keeps the last state it saw in memory, and compares on each change. It is a
container rather than a Cloudflare Worker because it holds listeners open for
the whole evening; its own README covers the detection rules and the three
things it deliberately does not say.

Django writes one type:

```bash
python manage.py publish_service_update --event <firestore event id> \
    --title "Counting has paused" \
    --body "The Electoral Commission has paused the count until 10.30 pm." \
    --dry-run
```

`--url` adds a link, and `--url-behaviour` says whether it navigates within the
site (`internal`, the default) or opens a new tab (`external`). `--id`
overwrites an existing announcement, so a wrong one can be corrected rather
than contradicted by a second entry. The push gate applies as it does
everywhere else, and `--dry-run` prints the document without writing it.

### There is no archive, deliberately

Django holds no copy of the feed and publishes none of it. Nothing of it
reaches R2, so an archived election shows no feed at all rather than a
published copy of one, and elections counted before this existed will never
have one. Turning `is_live` off takes the feed off the page with the rest of
the live transport.

### Before the night

The rule and the composite index are in `firestore.rules` and
`firestore.indexes.json` and deploy with everything else:

```bash
firebase deploy --only firestore:rules,firestore:indexes
```

Without the rule the catch-all deny blocks every read; without the index
(`event_id` ascending, `timestamp` descending) the query fails. An index built
for the first time under load takes minutes the evening will not have.

## Cost

Firestore bills per document read, and re-bills every changed document a
listener sees. Listeners are therefore scoped to what a page actually shows:

The national party vote is subscribed for the whole of a live count, on every
page. Anything beyond that is asked for by the page that needs it, and released
when that page closes.

| Page | Extra documents | Reads per client over a six-hour night |
|---|---|---|
| Overview | 0 — the national subscription is all it renders | ~180 |
| Electorate detail | 2 | ~360 while open |
| Candidates list | 144 | ~26,000 while open |
| Electorates list | 144 | ~26,000 while open |

The Overview is the page people leave open all evening, which is why it is the
one kept to a single document. The two list pages are the expensive ones, and
are deliberately not subscribed unless open.

**Reference data usually dominates all of this.** It is read once per visitor:
around 700 documents when it comes from Firestore, and none at all when either
the event document or the manifest names it on R2. Publishing it is the single
largest thing you can do to the bill.

**The feed is the one cost that scales with what happens** rather than with
what exists. Opening a page is 20 reads for the window, and so is every
reconnect; after that every entry written is one read for every page still
open. Twenty thousand open pages and three thousand entries is roughly 60M
reads, or about US$18–36 for the night. There is no way to batch that away —
the worker batching its writes keeps its own round trips down, but each entry
is still a read for each reader.

## Safety

Two environment gates, both defaulting to `false`, and both to be set to `true`
**in production only**. Every environment carries the same credentials — one
Firebase service account, and the same R2 keys, because the same bucket serves
media — so the credentials themselves protect nothing.

| Setting | Gates |
|---|---|
| `FIREBASE_PUSH_ENABLED` | Every write to Firestore |
| `ELECTIONS_PUBLISH_ENABLED` | Every write to the R2 snapshot bucket |

`ELECTIONS_PUBLISH_ENABLED` is enforced when the R2 writer is constructed, so
nothing can reach the live bucket without it — not a signal, not an admin
action, not a management command, not a test. Publishing with `--local`, and
`--dry-run` anywhere, are never gated.

This matters more than it looks. Saving a results version queues a manifest
rewrite, and the manifest is rebuilt from whatever versions the *current*
database knows about. A development database saving one row would otherwise
publish a manifest describing only that row, and the live site would show
nothing at all.

Django always writes to Firestore with `set(payload, merge=True)` against a
known document id, and never with `add()`. On the event document a replacing
write would drop `refdata_built`, which is the worker's; on an `election_*`
document it would drop everything the worker put there. Django never writes
`refdata_built` itself for the same reason: its own copy is only as current as
the last sync, so writing it back could overwrite the worker's answer with a
stale one. Merging is what lets the two sides share a
document without a coordination protocol.

## Troubleshooting

**The feed panel is empty, or says it could not load updates.** The entry is
almost certainly in Firestore; it is the client that cannot read it. The feed
needs two things deployed that no other part of the dashboard does, and
neither is visible in the Firebase console's own document view, because the
console bypasses both.

Check them in this order, because each produces an empty panel on its own:

1. **The read rule.** Confirm `match /feed/{document}` is in the *deployed*
   rules, not just in `firestore.rules`. Without it the catch-all deny at the
   bottom of the file refuses every read, and the browser console shows
   `permission-denied`. An unauthenticated read is the quickest check:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' \
     'https://firestore.googleapis.com/v1/projects/wheretheystand-elections/databases/(default)/documents/feed'
   ```

   `200` is deployed; `403` is not.

2. **The composite index** on `feed` (`event_id` ascending, `timestamp`
   descending). The query filters on one field and orders by another, so it
   cannot run without it. Firestore reports this as `failed-precondition` and
   says nothing about indexes. `firebase firestore:indexes --project
   wheretheystand-elections` lists what is actually deployed.

Both are fixed by the one deploy, and an index takes a few minutes to build
before the query starts working:

```bash
firebase deploy --only firestore:rules,firestore:indexes \
  --project wheretheystand-elections
```

Only once both are deployed is an empty panel worth investigating further. The
next thing to check is then `event_id` on the document, which must match the
results version's `firebase_id` exactly — the document **id** is only
cosmetic, and will keep the event it was first written for if the entry was
later corrected with `--id`.

**The dashboard says "Unknown candidate" next to live vote counts.** Reference
data has not reached the client. Check `refdata_built` on the Firestore event
document: until the worker sets it there are no names to be had, from anywhere.

**Reference data is being read from Firestore rather than R2.** Neither the
event document nor the manifest names a reference payload, so nothing has been
published for this version. Run `sync_live_elections` once. Costly, not broken.

If the manifest names one but the event document does not, the dashboard is
still reading from R2 — one fetch behind the manifest's cache lifetime rather
than off the listener. That means the Firestore write was refused or failed;
check the warning in the publish output and that `FIREBASE_PUSH_ENABLED` is
`true`. Costs nothing on the night.

**Candidates show the right names and tallies but do not link to their
profiles.** The persistent links were curated here and never pushed back. Run
`push_election_links`. Expect this to affect only clients reading reference data
from Firestore — the R2 copy always carries Django's own links, so the symptom
disappears once reference data is published, which can make it look
intermittent.

**Live mode never engages.** Both `is_live` and `firebase_id` must be set. Check
the *published manifest* rather than the database — the client reads the
manifest, which is up to thirty seconds old.

**The count was taken off live and pages show "No results available".** The
snapshot was not published before `is_live` was turned off. Run
`sync_live_elections`, which imports the results and rewrites the manifest.

**A change in the admin does not reach the site.** The manifest is rewritten by a
queued task, so check the Celery worker is running. Without a broker the save
still succeeds and the failure is logged, but nothing propagates; republish by
hand with `publish_election_snapshots`.

**A push says writes are disabled.** `FIREBASE_PUSH_ENABLED` is false. Correct
outside production.

**An electorate is missing from Firestore.** It probably has no `legacy_id`;
`push_persistent_to_firebase` logs a warning and skips those.

**Publishing dropped an election from the manifest.** It should not — the
manifest is rebuilt in full from `snapshot_paths`. A version that has never been
published has nothing to point at and is omitted until it is.

## Known gaps

- **Voting places and Calculations are stubs.** The Settings page collects MMP
  inputs that nothing consumes; there is no Sainte-Laguë engine.
- **`/parties/:id/elections` 404s.** The party page renders that tab when the
  elections flag is on, but no page file exists.
- **`persistent-*.json` is about 1.2 MB** and is inlined into every
  server-rendered election page. Worth trimming.
- **A legacy `events/{event_id}/` tree remains in R2** from the previous
  implementation, alongside the current `events/{election}/{version}/` scheme.
  `archived_url` on old event documents still points at it.
- **No `results_summary` document exists.** Highlighting close races on the home
  page needs one: a per-electorate margin in a single read, because the home
  page carries far more traffic than the dashboard. The client's store already
  has `applySummary()` waiting for it. It would also collapse the two list pages
  in the cost table above from 144 documents to one.
