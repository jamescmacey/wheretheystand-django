from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Bill, Vote


@override_settings(TURNSTILE_BYPASS_CODE="test-bypass-token")
class FeedbackCreateViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_create_feedback_with_turnstile_bypass(self):
        response = self.client.post(
            "/v2/feedback/",
            {
                "category": "feedback",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "message": "Hello from tests.",
                "turnstile": "test-bypass-token",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["category"], "feedback")
        self.assertEqual(response.data["name"], "Jane Doe")

    def test_rejects_invalid_turnstile(self):
        response = self.client.post(
            "/v2/feedback/",
            {
                "category": "general",
                "name": "Jane Doe",
                "email": "jane@example.com",
                "message": "Hello.",
                "turnstile": "not-valid",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("turnstile", response.data)


class LegacyMigrationViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.bill = Bill.objects.create(name="Test Bill", legacy_id=1001)
        self.vote = Vote.objects.create(
            bill=self.bill,
            legacy_id=2002,
            date=date(2024, 1, 15),
            reading=1,
            ayes=60,
            noes=59,
            abstentions=0,
            absentees=1,
        )

    def test_bill_legacy_migration_returns_uuid(self):
        response = self.client.get("/v2/migration/bills/1001/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.bill.id))

    def test_bill_legacy_migration_not_found(self):
        response = self.client.get("/v2/migration/bills/9999/")
        self.assertEqual(response.status_code, 404)

    def test_vote_legacy_migration_returns_uuid(self):
        response = self.client.get("/v2/migration/votes/2002/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.vote.id))

    def test_vote_legacy_migration_not_found(self):
        response = self.client.get("/v2/migration/votes/9999/")
        self.assertEqual(response.status_code, 404)


class ElectionResultsContractTests(TestCase):
    """The canonical shape served to election results clients.

    The same JSON reaches components from this API, from the R2 snapshots built
    off these serializers, and from Firestore during a live event. Firestore
    references entities by their Electoral Commission number, so these
    serializers must too -- a primary key here would silently split the contract
    in two.
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import datetime, timedelta, timezone as dt_timezone

        from .models import (
            Election, ElectionResultVersion, ElectionElectorate, ElectionParty,
            ElectionCandidate, ElectionVotingPlace, ResultsSet, Result,
        )

        nz = dt_timezone(timedelta(hours=13))
        cls.election = Election.objects.create(
            name="2023 General Election", polling_date=date(2023, 10, 14),
            polls_close=datetime(2023, 10, 14, 19, 0, tzinfo=nz))
        cls.version = ElectionResultVersion.objects.create(
            election=cls.election, name="Official count", is_primary=True)

        cls.electorate = ElectionElectorate.objects.create(
            results_version=cls.version, number=1, name="Auckland Central")
        cls.party = ElectionParty.objects.create(
            results_version=cls.version, number=5, name="Green Party",
            abbreviation="GP", registered=True)
        cls.candidate = ElectionCandidate.objects.create(
            results_version=cls.version, number=42, name="SMITH, Jane",
            electorate=cls.electorate, party=cls.party, list_pos=3)
        cls.voting_place = ElectionVotingPlace.objects.create(
            results_version=cls.version, number=4206,
            physical_electorate=cls.electorate, address="A hall",
            latitude=-36.8, longitude=174.7)

        cls.national = ResultsSet.objects.create(
            results_version=cls.version, results_level="national",
            results_category="party_votes", is_final=True,
            updated=datetime(2023, 10, 14, 22, 0, tzinfo=nz),
            total_votes_cast=2886000, percent_votes_cast=98.7)
        Result.objects.create(results_set=cls.national, party=cls.party,
                              count=219031, per_cent=7.6, list_seats=9,
                              electorate_seats=1, total_seats=10)
        # A line with neither a candidate nor a party, as informal-style rows
        # arrive from the feed.
        Result.objects.create(results_set=cls.national, count=17)

        cls.at_voting_place = ResultsSet.objects.create(
            results_version=cls.version, results_level="voting_place",
            results_category="candidate_votes", electorate=cls.electorate,
            voting_place=cls.voting_place,
            updated=datetime(2023, 10, 14, 20, 0, tzinfo=nz))

    def test_result_references_entities_by_number(self):
        from .views.election_results import ResultSerializer
        from .models import Result

        result = Result.objects.get(results_set=self.national, party=self.party)
        data = ResultSerializer(result).data
        self.assertEqual(data["party"], 5)
        self.assertIsInstance(data["party"], int)

    def test_result_renders_missing_entities_as_null(self):
        """Absent keys would break the contract; null is required."""
        from .views.election_results import ResultSerializer
        from .models import Result

        result = Result.objects.get(results_set=self.national, count=17)
        data = ResultSerializer(result).data
        self.assertIn("candidate", data)
        self.assertIn("party", data)
        self.assertIsNone(data["candidate"])
        self.assertIsNone(data["party"])

    def test_results_set_references_entities_by_number(self):
        from .views.election_results import ResultsSetSerializer

        data = ResultsSetSerializer(self.at_voting_place).data
        self.assertEqual(data["electorate"], 1)
        self.assertEqual(data["voting_place"], 4206)
        self.assertEqual(data["voting_place_electorate"], 1)

    def test_results_set_keys_match_across_shapes(self):
        """A national set and a voting place set carry identical keys."""
        from .views.election_results import ResultsSetSerializer

        national = ResultsSetSerializer(self.national).data
        voting_place = ResultsSetSerializer(self.at_voting_place).data
        self.assertEqual(set(national), set(voting_place))
        self.assertIsNone(national["electorate"])
        self.assertIsNone(national["voting_place_electorate"])

    def test_canonical_key_identifies_a_results_set(self):
        from .views.election_results import ResultsSetSerializer

        self.assertEqual(
            ResultsSetSerializer(self.national).data["key"],
            "national:party_votes:-:-:-")
        self.assertEqual(
            ResultsSetSerializer(self.at_voting_place).data["key"],
            "voting_place:candidate_votes:1:4206:-")

    def test_statistics_are_nested_and_complete(self):
        from .models import ResultsSet
        from .views.election_results import ResultsSetSerializer

        data = ResultsSetSerializer(self.national).data
        self.assertIsInstance(data["statistics"], dict)
        self.assertEqual(set(data["statistics"]), set(ResultsSet.STATISTICS_FIELDS))
        self.assertEqual(data["statistics"]["total_votes_cast"], 2886000)
        # The flat columns are an implementation detail of this database.
        self.assertNotIn("total_votes_cast", data)

    def test_updated_timestamp_supports_staleness_checks(self):
        from .views.election_results import ResultsSetSerializer

        data = ResultsSetSerializer(self.national).data
        self.assertEqual(data["updated_timestamp"], self.national.updated.timestamp())

    def test_reference_entities_omit_internal_fields(self):
        from .views.election_results import (
            ElectionCandidateSerializer, ElectionPartySerializer,
            ElectionVotingPlaceSerializer,
        )

        candidate = ElectionCandidateSerializer(self.candidate).data
        self.assertEqual(candidate["electorate"], 1)
        self.assertEqual(candidate["party"], 5)
        self.assertNotIn("results_version", candidate)
        self.assertNotIn("created_at", candidate)

        party = ElectionPartySerializer(self.party).data
        # ElectionParty has no `party` relation; the serializer used to declare
        # one, which DRF silently dropped.
        self.assertNotIn("party", party)
        self.assertIn("persistent_party", party)

        self.assertEqual(
            ElectionVotingPlaceSerializer(self.voting_place).data["physical_electorate"], 1)

    def test_reference_data_excludes_voting_places_by_default(self):
        """Several thousand voting places would dominate the payload."""
        client = APIClient()
        url = f"/v2/elections/{self.election.slug}/{self.version.slug}/reference-data/"

        default = client.get(url)
        self.assertEqual(default.status_code, 200)
        self.assertEqual(default.data["voting_places"], [])
        self.assertEqual(len(default.data["candidates"]), 1)

        included = client.get(url, {"include": "voting_places"})
        self.assertEqual(len(included.data["voting_places"]), 1)

    def test_results_endpoint_serves_the_contract(self):
        client = APIClient()
        response = client.get(
            f"/v2/elections/{self.election.slug}/default/results/")
        self.assertEqual(response.status_code, 200)
        sets = {item["key"]: item for item in response.data["results_sets"]}
        self.assertIn("national:party_votes:-:-:-", sets)
        national = sets["national:party_votes:-:-:-"]
        self.assertEqual(national["transport"], "snapshot")
        self.assertEqual(
            sorted(r["party"] for r in national["results"] if r["party"]), [5])


from datetime import datetime, timedelta, timezone as dt_timezone
import json
import pathlib
import tempfile

from .models.elections import (
    Election, ElectionResultVersion, ElectionElectorate, ElectionParty,
    ElectionCandidate, ElectionVotingPlace, ElectorateIncumbent, PartyIncumbent,
    ResultsSet, Result, PersistentParty,
    PersistentCandidate, PersistentVotingPlace,
)
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

from .snapshots import builders, publisher


class SnapshotPublisherTests(TestCase):
    """The static snapshots the client reads instead of calling this API.

    Django is the source of truth for results but must not serve them to the
    public during an event, so these payloads are published to R2 and read from
    the edge. The properties that matter are ordering (the manifest last, so a
    failed publish is invisible) and content addressing (so republishing
    unchanged data is free and changed data cannot be served stale).
    """
    @classmethod
    def setUpTestData(cls):
        nz = dt_timezone(timedelta(hours=13))
        cls.election = Election.objects.create(
            name="2023 General Election", polling_date=date(2023, 10, 14),
            polls_close=datetime(2023, 10, 14, 19, 0, tzinfo=nz))
        cls.v = ElectionResultVersion.objects.create(
            election=cls.election, name="Official count", is_primary=True,
            access_mode="firebase", firebase_id="ge2023_e9")
        pp = PersistentParty.objects.create(display_name="Green Party", colour="#0ac958")
        el = ElectionElectorate.objects.create(results_version=cls.v, number=1, name="Auckland Central")
        pa = ElectionParty.objects.create(results_version=cls.v, number=5, name="Green Party",
                                          persistent_party=pp)
        ca = ElectionCandidate.objects.create(results_version=cls.v, number=42,
                                              name="SMITH, Jane", electorate=el, party=pa)
        vp = ElectionVotingPlace.objects.create(results_version=cls.v, number=4206,
                                                physical_electorate=el, address="A hall",
                                                latitude=-36.8, longitude=174.7)
        nat = ResultsSet.objects.create(results_version=cls.v, results_level="national",
                                        results_category="party_votes", is_final=True,
                                        updated=datetime(2023, 10, 14, 22, 0, tzinfo=nz),
                                        total_votes_cast=2886000)
        Result.objects.create(results_set=nat, party=pa, count=219031, per_cent=7.6, total_seats=10)
        vps = ResultsSet.objects.create(results_version=cls.v, results_level="voting_place",
                                        results_category="candidate_votes", electorate=el,
                                        voting_place=vp,
                                        updated=datetime(2023, 10, 14, 20, 0, tzinfo=nz))
        Result.objects.create(results_set=vps, candidate=ca, count=115)

        # A hall in Auckland Central also issues Tamaki Makaurau's ballots, which
        # is the ordinary case and the reason the per-place sharding exists: this
        # set lands in electorate 2's shard, not electorate 1's.
        cls.maori = ElectionElectorate.objects.create(
            results_version=cls.v, number=2, name="Tamaki Makaurau")
        away = ResultsSet.objects.create(
            results_version=cls.v, results_level="voting_place",
            results_category="party_votes", electorate=cls.maori, voting_place=vp,
            firebase_id="set-away",
            updated=datetime(2023, 10, 14, 20, 0, tzinfo=nz))
        Result.objects.create(results_set=away, party=pa, count=40)

        # Two sets for the same place, electorate and category, which is how
        # advance and polling-day votes have been published before. They are
        # separated only by the last component of the canonical key.
        cls.split_one = ResultsSet.objects.create(
            results_version=cls.v, results_level="voting_place",
            results_category="party_votes", electorate=el, voting_place=vp,
            firebase_id="set-advance",
            updated=datetime(2023, 10, 14, 20, 0, tzinfo=nz))
        Result.objects.create(results_set=cls.split_one, party=pa, count=70)
        cls.split_two = ResultsSet.objects.create(
            results_version=cls.v, results_level="voting_place",
            results_category="party_votes", electorate=el, voting_place=vp,
            firebase_id="set-polling-day",
            updated=datetime(2023, 10, 14, 21, 0, tzinfo=nz))
        Result.objects.create(results_set=cls.split_two, party=pa, count=45)

    def test_local_publish_produces_a_navigable_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            writer = publisher.LocalWriter(root)
            published = publisher.publish_all(writer, include_voting_places=True)

            manifest = json.loads((root / "manifest.json").read_text())
            self.assertEqual(len(manifest["elections"]), 1)
            entry = manifest["elections"][0]["results_versions"][0]
            self.assertEqual(entry["firebase_id"], "ge2023_e9")
            self.assertEqual(entry["access_mode"], "firebase")
            # is_live does not exist yet, so live mode stays off.
            self.assertFalse(entry["is_live"])

            # Every path the manifest names must actually exist.
            for name in ("persistent", "reference", "results"):
                self.assertTrue((root / entry["paths"][name]).is_file(),
                                f"{name} missing at {entry['paths'][name]}")

            results = json.loads((root / entry["paths"]["results"]).read_text())
            keys = {s["key"] for s in results["results_sets"]}
            self.assertIn("national:party_votes:-:-:-", keys)
            # Voting place sets belong in their own files, not the main payload.
            self.assertNotIn("voting_place:candidate_votes:1:4206:-", keys)

            by_electorate = root / entry["paths"]["voting_places"]["by_electorate_base"] / "1.json"
            vp_payload = json.loads(by_electorate.read_text())
            self.assertEqual(vp_payload["results_sets"][0]["voting_place"], 4206)

            # Everything the hall counted, for every electorate it served --
            # which the by-electorate shards cannot answer between them without
            # fetching all of them.
            by_place = root / entry["paths"]["voting_places"]["by_place_base"] / "4206.json"
            place_payload = json.loads(by_place.read_text())
            self.assertEqual(entry["paths"]["voting_places"]["by_place_count"], 1)

            sets = place_payload["results_sets"]
            self.assertEqual({s["voting_place"] for s in sets}, {4206})
            self.assertEqual({s["electorate"] for s in sets}, {1, 2})
            # Where the place stands, as against whose votes these are.
            self.assertEqual({s["voting_place_electorate"] for s in sets}, {1})

            reference = json.loads((root / entry["paths"]["reference"]).read_text())
            self.assertEqual(reference["candidates"][0]["party"], 5)
            self.assertEqual(reference["voting_places"], [])

    def test_sets_split_across_reports_keep_separate_keys(self):
        """Advance and polling-day votes for one place must both survive.

        The client holds one entry per canonical key and keeps whichever tally
        carries the later timestamp, so two sets sharing a key is a tally
        dropped with nothing to show it. The last component of the key is what
        separates them.
        """
        by_place = builders.build_voting_place_results(self.v)
        sets = by_place[4206]["results_sets"]

        home_party_votes = [s for s in sets
                            if s["electorate"] == 1 and s["results_category"] == "party_votes"]
        self.assertEqual(len(home_party_votes), 2)
        self.assertEqual(len({s["key"] for s in home_party_votes}), 2)
        # Together, not either one of them.
        self.assertEqual(sum(s["results"][0]["count"] for s in home_party_votes), 115)

    def test_colliding_voting_place_sets_are_reported(self):
        """The condition under which the client silently loses a tally.

        Nothing populates result_number, so the Firestore document id stands in.
        Two sets with neither leaves them indistinguishable, which is worth a
        warning before an event rather than a total that looks slightly low
        during one.
        """
        self.assertEqual(builders.find_colliding_voting_place_sets(self.v), {})

        ResultsSet.objects.filter(
            pk__in=[self.split_one.pk, self.split_two.pk]).update(firebase_id=None)

        collisions = builders.find_colliding_voting_place_sets(self.v)
        self.assertEqual(list(collisions), ["voting_place:party_votes:1:4206:-"])
        self.assertEqual(len(collisions["voting_place:party_votes:1:4206:-"]), 2)

    def test_manifest_carries_the_card_image_url(self):
        """The social card is published as a URL, not as a stored path.

        The client only ever reads the manifest, so a path into the media
        bucket would be no use to it.
        """
        field = ElectionResultVersion._meta.get_field('card_image')
        with tempfile.TemporaryDirectory() as tmp:
            media = FileSystemStorage(location=tmp,
                                      base_url='https://media.example/')
            with patch.object(field, 'storage', media):
                self.v.card_image.save('card.png', ContentFile(b'png bytes'),
                                       save=False)
                entry = builders.build_version_entry(self.v, {})

        self.assertEqual(
            entry['card_image_url'],
            f"https://media.example/elections/cards/{self.v.id}/card.png")

    def test_manifest_card_image_url_is_null_without_a_card(self):
        """Most versions never get one, and the key must still be there."""
        entry = builders.build_version_entry(self.v, {})
        self.assertIsNone(entry['card_image_url'])

    def test_manifest_is_written_last(self):
        """A failed publish must not leave the manifest pointing at nothing."""
        writer = publisher.DryRunWriter()
        publisher.publish_all(writer)
        self.assertEqual(writer.written[-1], "manifest.json")

    def test_unchanged_data_publishes_to_the_same_paths(self):
        """Content addressing makes republishing idempotent."""
        first, second = publisher.DryRunWriter(), publisher.DryRunWriter()
        a = publisher.publish_all(first)
        b = publisher.publish_all(second)
        self.assertEqual(a, b)
        self.assertEqual(first.written, second.written)

    def test_changed_data_publishes_to_a_new_path(self):
        before = publisher.publish_all(publisher.DryRunWriter())
        ResultsSet.objects.filter(results_level="national").update(total_votes_cast=9)
        after = publisher.publish_all(publisher.DryRunWriter())
        key = f"{self.election.slug}/{self.v.slug}"
        self.assertNotEqual(before[key]["results"], after[key]["results"])

    def test_results_are_always_content_addressed(self):
        """There is no rolling results file for anything to go stale on.

        Clients take live tallies from Firestore, so the only results object
        published is the immutable one they fall back to when a count ends.
        """
        writer = publisher.DryRunWriter()
        published = publisher.publish_all(writer)
        key = f"{self.election.slug}/{self.v.slug}"
        self.assertRegex(published[key]["results"], r"/results-[0-9a-f]{12}\.json$")
        self.assertNotIn(
            f"events/{self.election.slug}/{self.v.slug}/results-latest.json",
            writer.written)

    def test_persistent_data_is_shared_across_events(self):
        """Published at the root, so every event references one object."""
        writer = publisher.DryRunWriter()
        published = publisher.publish_all(writer)
        key = f"{self.election.slug}/{self.v.slug}"
        self.assertFalse(published[key]["persistent"].startswith("events/"))


class FirebasePushTests(TestCase):
    """What Django sends outward to Firestore.

    Django owns the event's own description and the entities that persist across
    elections. The worker owns everything else on those documents, which is why
    every write here merges rather than replaces.
    """

    @classmethod
    def setUpTestData(cls):
        nz = dt_timezone(timedelta(hours=13))
        cls.election = Election.objects.create(
            name="Ilam By-election", election_type="by-election",
            polling_date=date(2026, 3, 7),
            polls_close=datetime(2026, 3, 7, 19, 0, tzinfo=nz))
        cls.left = PersistentParty.objects.create(
            display_name="Left Party", firebase_id="pp_left", colour="#ff0000")
        cls.right = PersistentParty.objects.create(
            display_name="Right Party", firebase_id="pp_right", colour="#0000ff")
        cls.earlier = ElectionResultVersion.objects.create(
            election=cls.election, name="Preliminary", firebase_id="by2026_prelim")
        cls.version = ElectionResultVersion.objects.create(
            election=cls.election, name="Official count", is_primary=True,
            access_mode="firebase", is_live=True,
            bloc_order_left=[str(cls.left.id)],
            bloc_order_right=[str(cls.right.id)],
            comparison_version_ids=[str(cls.earlier.id)])

    def test_event_document_carries_curated_fields(self):
        from .firebase import push

        document = push.build_event_document(self.version)
        self.assertEqual(document["name"], "Official count")
        self.assertTrue(document["is_live"])
        # Django spells this with a hyphen; the Firestore enum does not.
        self.assertEqual(document["election_type"], "by_election")
        # Ordered UUID lists resolve to the ids Firestore uses.
        self.assertEqual(document["bloc_order_left"], ["pp_left"])
        self.assertEqual(document["bloc_order_right"], ["pp_right"])
        self.assertEqual(document["comparison_events"], ["by2026_prelim"])

    def test_event_document_never_claims_reference_data(self):
        """refdata_built belongs to the worker; a merge must not overwrite it."""
        from .firebase import push

        self.assertNotIn("refdata_built", push.build_event_document(self.version))

    def test_event_document_id_is_stable_without_a_firebase_id(self):
        from .firebase import push

        self.assertEqual(
            push.event_document_id(self.version), "ilam-by-election_official-count")
        self.version.firebase_id = "by2026"
        self.assertEqual(push.event_document_id(self.version), "by2026")

    def test_push_refuses_to_write_when_disabled(self):
        """Every environment shares one service account, so this gate matters."""
        from .firebase import push

        with override_settings(FIREBASE_PUSH_ENABLED=False):
            with self.assertRaises(push.FirebasePushDisabled):
                push.push_event(self.version.id)
            with self.assertRaises(push.FirebasePushDisabled):
                push.push_persistent_parties()

    def test_dry_run_needs_no_credentials_and_writes_nothing(self):
        from .firebase import push

        with override_settings(FIREBASE_PUSH_ENABLED=False):
            self.assertEqual(push.push_persistent_parties(dry_run=True), 2)

    def test_unknown_ids_in_ordered_lists_are_rejected(self):
        from django.core.exceptions import ValidationError

        self.version.bloc_order_right = ["4b1f4c3e-0000-0000-0000-000000000000"]
        with self.assertRaises(ValidationError) as caught:
            self.version.clean()
        self.assertIn("bloc_order_right", caught.exception.message_dict)


class ServiceUpdateTests(TestCase):
    """The one feed entry Django writes.

    Everything else in `feed` comes from election-feed-worker. Django holds no
    copy of any of it and archives none of it, so the only thing to get right
    here is the shape of the document the client reads.
    """

    def test_announcement_carries_the_shared_fields(self):
        from .firebase import push

        document = push.build_service_update("ge2026", "Counting has paused", "Until 10.30 pm.")
        self.assertEqual(document["event_id"], "ge2026")
        self.assertEqual(document["type"], "SERVICE_ANNOUNCEMENT")
        self.assertEqual(document["title"], "Counting has paused")
        self.assertEqual(document["body"], "Until 10.30 pm.")
        self.assertIsInstance(document["timestamp_seconds"], int)
        # An announcement comes from a person, not from a tally.
        self.assertIsNone(document["source_timestamp"])

    def test_url_behaviour_decides_how_the_link_opens(self):
        from .firebase import push

        internal = push.build_service_update(
            "ge2026", "Title", "", "/elections", "internal")
        self.assertFalse(internal["metadata"]["external"])

        external = push.build_service_update(
            "ge2026", "Title", "", "https://example.org", "external")
        self.assertTrue(external["metadata"]["external"])

    def test_an_announcement_without_a_url_opens_nothing(self):
        from .firebase import push

        document = push.build_service_update("ge2026", "Title", "Body")
        self.assertIsNone(document["metadata"]["url"])
        self.assertFalse(document["metadata"]["external"])

    def test_an_unknown_url_behaviour_is_rejected(self):
        from .firebase import push

        with self.assertRaises(ValueError):
            push.build_service_update("ge2026", "Title", "", "/x", "popup")

    def test_ids_are_ordered_and_do_not_collide(self):
        from .firebase import push

        first = push.service_update_id("ge2026")
        second = push.service_update_id("ge2026")
        self.assertTrue(first.startswith("ge2026:SERVICE_ANNOUNCEMENT:"))
        # Millisecond resolution, so two in the same second are two documents.
        self.assertLessEqual(first, second)

    def test_posting_refuses_to_write_when_disabled(self):
        from .firebase import push

        with override_settings(FIREBASE_PUSH_ENABLED=False):
            with self.assertRaises(push.FirebasePushDisabled):
                push.push_service_update("ge2026", "Title", "Body")

    def test_a_dry_run_needs_no_credentials_and_writes_nothing(self):
        from .firebase import push

        with override_settings(FIREBASE_PUSH_ENABLED=False):
            document_id = push.push_service_update(
                "ge2026", "Title", "Body", dry_run=True)
        self.assertTrue(document_id.startswith("ge2026:SERVICE_ANNOUNCEMENT:"))


class SnapshotManifestTests(TestCase):
    """Publishing one event must not remove the others from the manifest."""

    @classmethod
    def setUpTestData(cls):
        nz = dt_timezone(timedelta(hours=13))
        cls.old = Election.objects.create(
            name="2023 General Election", polling_date=date(2023, 10, 14),
            polls_close=datetime(2023, 10, 14, 19, 0, tzinfo=nz))
        cls.old_version = ElectionResultVersion.objects.create(
            election=cls.old, name="Official count", is_primary=True)
        cls.new = Election.objects.create(
            name="2026 General Election", polling_date=date(2026, 5, 16),
            polls_close=datetime(2026, 5, 16, 19, 0, tzinfo=nz))
        cls.new_version = ElectionResultVersion.objects.create(
            election=cls.new, name="Election night", is_primary=True,
            access_mode="firebase", firebase_id="ge2026", is_live=True)

    def _manifest(self, writer, root):
        return json.loads((root / "manifest.json").read_text())

    def test_publishing_one_version_keeps_the_others_in_the_manifest(self):
        from .snapshots import publisher

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)

            # Publish everything, recording where each version landed.
            publisher.publish_all(publisher.LocalWriter(root))
            first = self._manifest(None, root)
            self.assertEqual(len(first["elections"]), 2)

            # Now republish only one event, as ending a count does.
            publisher.publish_all(
                publisher.LocalWriter(root),
                versions=[self.new_version])
            second = self._manifest(None, root)

        slugs = {e["slug"] for e in second["elections"]}
        self.assertEqual(slugs, {"2023-general-election", "2026-general-election"})

    def test_published_paths_are_recorded_for_later_manifests(self):
        from .snapshots import publisher

        with tempfile.TemporaryDirectory() as tmp:
            publisher.publish_all(publisher.LocalWriter(pathlib.Path(tmp)))

        self.old_version.refresh_from_db()
        self.assertIn("results", self.old_version.snapshot_paths)
        self.assertIsNotNone(self.old_version.last_snapshot_published_at)

    def test_a_local_publish_does_not_claim_to_be_the_published_location(self):
        from .snapshots import publisher

        with tempfile.TemporaryDirectory() as tmp:
            publisher.publish_all(
                publisher.LocalWriter(pathlib.Path(tmp)), record=False)

        self.old_version.refresh_from_db()
        self.assertEqual(self.old_version.snapshot_paths, {})


@override_settings(FIREBASE_PUSH_ENABLED=True)
class ElectionLinkPushTests(TestCase):
    """Curated persistent links, written back onto the worker's reference data.

    The worker matches what it recognises and leaves the rest null. Those are
    decided here, and until they are pushed they exist only here -- so a client
    reading reference data from Firestore renders the right name and tally but
    cannot link through to the person.
    """

    @classmethod
    def setUpTestData(cls):
        nz = dt_timezone(timedelta(hours=13))
        cls.election = Election.objects.create(
            name="2026 General Election", polling_date=date(2026, 11, 7),
            polls_close=datetime(2026, 11, 7, 19, 0, tzinfo=nz))
        cls.version = ElectionResultVersion.objects.create(
            election=cls.election, name="Election night", is_primary=True,
            access_mode="firebase", firebase_id="ge2026_prelim")

        party = PersistentParty.objects.create(
            display_name="Green Party", firebase_id="pp_green")
        cls.election_party = ElectionParty.objects.create(
            results_version=cls.version, number=5, name="Green Party",
            firebase_id="ep_green", persistent_party=party)

        cls.person = PersistentCandidate.objects.create(
            display_name="SMITH, Jane", firebase_id="pc_smith")
        cls.candidate = ElectionCandidate.objects.create(
            results_version=cls.version, number=42, name="SMITH, Jane",
            firebase_id="ec_smith", party=cls.election_party,
            persistent_candidate=cls.person)

    def _pushed(self, **kwargs):
        """Run a push with the Firestore client stubbed, returning the writes."""
        from .firebase import push

        writes = []

        def record(db, collection, document_id, payload, dry_run):
            writes.append((collection, document_id, payload))
            return document_id

        with patch.object(push, "get_firestore_client", lambda: object()), \
                patch.object(push, "_write", record):
            push.push_election_links(self.version, **kwargs)
        return writes

    def test_a_curated_link_reaches_the_worker_s_document(self):
        writes = self._pushed(only=["candidates"])
        self.assertEqual(
            writes, [("election_candidates", "ec_smith",
                      {"persistent_candidate_id": "pc_smith"})])

    def test_only_the_link_field_is_written(self):
        """Everything else on these documents belongs to the worker."""
        for _, _, payload in self._pushed():
            self.assertEqual(len(payload), 1)
            self.assertTrue(next(iter(payload)).startswith("persistent_"))

    def test_unmatched_rows_are_left_alone(self):
        """A null link is the worker's business, not something to overwrite."""
        ElectionCandidate.objects.create(
            results_version=self.version, number=43, name="JONES, Sam",
            firebase_id="ec_jones")
        writes = self._pushed(only=["candidates"])
        self.assertEqual([document for _, document, _ in writes], ["ec_smith"])

    def test_a_row_with_no_firestore_document_is_skipped(self):
        """Created in Django rather than imported, so there is nowhere to write."""
        ElectionCandidate.objects.create(
            results_version=self.version, number=44, name="TAI, Aroha",
            persistent_candidate=self.person)
        writes = self._pushed(only=["candidates"])
        self.assertEqual([document for _, document, _ in writes], ["ec_smith"])

    def test_a_persistent_record_never_pushed_is_skipped(self):
        """Writing its Django UUID would name a document that does not exist."""
        self.person.firebase_id = None
        self.person.save()
        self.assertEqual(self._pushed(only=["candidates"]), [])

    def test_pushing_is_refused_where_writes_are_disabled(self):
        from .firebase import push

        with override_settings(FIREBASE_PUSH_ENABLED=False):
            with self.assertRaises(push.FirebasePushDisabled):
                push.push_election_links(self.version)

    def test_electorate_links_carry_the_django_uuid(self):
        """One identity space: Firestore names an electorate by its UUID now."""
        from .models import Electorate

        electorate = Electorate.objects.create(
            name="Ilam", legacy_id=17, region="Canterbury",
            valid_from=date(2020, 1, 1))
        ElectionElectorate.objects.create(
            results_version=self.version, number=1, name="Ilam",
            firebase_id="ee_ilam", electorate=electorate)

        self.assertEqual(
            self._pushed(only=["electorates"]),
            [("election_electorates", "ee_ilam",
              {"persistent_electorate_id": str(electorate.id)})])


class _FakeDocument:
    def __init__(self, document_id, deleted):
        self.id = document_id
        self._deleted = deleted

    def delete(self):
        self._deleted.append(self.id)


class _FakeCollection:
    def __init__(self, ids, deleted):
        self._ids = ids
        self._deleted = deleted

    def stream(self):
        return [_FakeDocument(i, self._deleted) for i in self._ids]

    def document(self, document_id):
        return _FakeDocument(str(document_id), self._deleted)


class _FakeFirestore:
    """Just enough Firestore to exercise the prune command's arithmetic."""

    def __init__(self, by_collection):
        self.by_collection = by_collection
        self.deleted = []

    def collection(self, name):
        return _FakeCollection(self.by_collection.get(name, []), self.deleted)


@override_settings(FIREBASE_PUSH_ENABLED=True)
class PrunePersistentDocumentsTests(TestCase):
    """Clearing the documents left behind by the move to Django UUIDs.

    The report is the whole safety mechanism here: it is what someone reads
    before running the one command in this codebase that destroys data.
    """

    @classmethod
    def setUpTestData(cls):
        cls.party = PersistentParty.objects.create(
            display_name="Green Party", firebase_id="5f2b1c9e4d3a2b1c9e4d3a2b")

    def _run(self, documents, *args):
        from django.core.management import call_command
        from io import StringIO

        fake = _FakeFirestore(documents)
        out = StringIO()
        with patch('wts_app.management.commands.prune_persistent_documents'
                   '.get_firestore_client', lambda: fake):
            call_command('prune_persistent_documents', '--only', 'parties',
                         *args, stdout=out)
        return out.getvalue(), fake

    def test_the_report_states_the_collection_size(self):
        """679 to delete means something different out of 1358 than out of 679."""
        output, _ = self._run({
            'persistent_parties': ['5f2b1c9e4d3a2b1c9e4d3a2b', str(self.party.id)],
        })
        self.assertIn('persistent_parties: 2 document(s)', output)
        self.assertIn('1 at a current Django id, of 1 entities', output)
        self.assertIn('1 to delete', output)

    def test_nothing_is_deleted_without_apply(self):
        _, fake = self._run({
            'persistent_parties': ['5f2b1c9e4d3a2b1c9e4d3a2b', str(self.party.id)],
        })
        self.assertEqual(fake.deleted, [])

    def test_only_the_stale_document_is_deleted(self):
        _, fake = self._run({
            'persistent_parties': ['5f2b1c9e4d3a2b1c9e4d3a2b', str(self.party.id)],
        }, '--apply')
        self.assertEqual(fake.deleted, ['5f2b1c9e4d3a2b1c9e4d3a2b'])

    def test_it_refuses_when_an_entity_was_never_migrated(self):
        """Deleting the old document would remove it from Firestore entirely."""
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as caught:
            self._run({'persistent_parties': ['5f2b1c9e4d3a2b1c9e4d3a2b']}, '--apply')
        self.assertIn('align_firebase_ids', str(caught.exception))

    def test_the_refusal_happens_before_any_delete(self):
        from django.core.management.base import CommandError

        try:
            _, fake = self._run(
                {'persistent_parties': ['5f2b1c9e4d3a2b1c9e4d3a2b']}, '--apply')
        except CommandError:
            pass
        # Nothing was removed: the guard runs across every collection first.
        self.assertEqual(
            PersistentParty.objects.filter(id=self.party.id).count(), 1)


@override_settings(FIREBASE_PUSH_ENABLED=True)
class FirebaseIdAlignmentTests(TestCase):
    """Collapsing two identity spaces into one.

    Persistent documents were keyed by Mongo ObjectId, and electorates by an
    integer, neither of which is a Django primary key. Aligning them on the UUID
    removes the translation the client used to have to do.
    """

    @classmethod
    def setUpTestData(cls):
        cls.aligned = PersistentParty.objects.create(display_name="Aligned Party")
        cls.aligned.firebase_id = str(cls.aligned.id)
        cls.aligned.save()
        cls.legacy = PersistentParty.objects.create(
            display_name="Legacy Party", firebase_id="5f2b1c9e4d3a2b1c9e4d3a2b")
        cls.candidate = PersistentCandidate.objects.create(
            display_name="SMITH, Jane", firebase_id="5f2b1c9e4d3a2b1c9e4d3a2c")

    def test_alignment_rewrites_only_what_differs(self):
        from django.core.management import call_command
        from io import StringIO

        call_command('align_firebase_ids', '--no-push', stdout=StringIO())

        self.legacy.refresh_from_db()
        self.candidate.refresh_from_db()
        self.aligned.refresh_from_db()
        self.assertEqual(self.legacy.firebase_id, str(self.legacy.id))
        self.assertEqual(self.candidate.firebase_id, str(self.candidate.id))
        self.assertEqual(self.aligned.firebase_id, str(self.aligned.id))

    def test_a_dry_run_changes_nothing(self):
        from django.core.management import call_command
        from io import StringIO

        call_command('align_firebase_ids', '--dry-run', stdout=StringIO())

        self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.firebase_id, "5f2b1c9e4d3a2b1c9e4d3a2b")

    def test_running_twice_is_a_no_op(self):
        from django.core.management import call_command
        from io import StringIO

        call_command('align_firebase_ids', '--no-push', stdout=StringIO())
        second = StringIO()
        call_command('align_firebase_ids', '--no-push', stdout=second)

        self.assertIn("Re-keyed 0 row(s)", second.getvalue())

    def test_the_dry_run_mentions_electorates(self):
        """They have nothing to re-key here, which makes silence look like a bug."""
        from django.core.management import call_command
        from io import StringIO

        from .models import Electorate

        Electorate.objects.create(
            name="Ilam", legacy_id=17, region="Canterbury",
            valid_from=date(2020, 1, 1))

        out = StringIO()
        call_command('align_firebase_ids', '--dry-run', stdout=out)
        self.assertIn('electorates: 1', out.getvalue())

    def test_the_whole_command_re_keys_electorates_too(self):
        """Electorates have no firebase_id column, so they are easy to miss."""
        from django.core.management import call_command
        from io import StringIO

        from .firebase import push
        from .models import Electorate

        electorate = Electorate.objects.create(
            name="Ilam", legacy_id=17, region="Canterbury",
            valid_from=date(2020, 1, 1))
        election = Election.objects.create(
            name="2026 General Election", polling_date=date(2026, 11, 7),
            polls_close=datetime(2026, 11, 7, 19, 0,
                                 tzinfo=dt_timezone(timedelta(hours=13))))
        version = ElectionResultVersion.objects.create(
            election=election, name="Election night", is_primary=True,
            access_mode="firebase", firebase_id="ge2026_prelim")
        ElectionElectorate.objects.create(
            results_version=version, number=1, name="Ilam",
            firebase_id="ee_ilam", electorate=electorate)

        writes = []

        def record(db, collection, document_id, payload, dry_run):
            writes.append((collection, str(document_id), payload))
            return document_id

        with patch.object(push, "get_firestore_client", lambda: object()), \
                patch.object(push, "_write", record):
            call_command('align_firebase_ids', stdout=StringIO())

        # The persistent document moves to the UUID...
        self.assertIn(
            ("persistent_electorates", str(electorate.id)),
            [(collection, document) for collection, document, _ in writes])

        # ...and the election row that refers to it is re-pointed.
        self.assertIn(
            ("election_electorates", "ee_ilam",
             {"persistent_electorate_id": str(electorate.id)}),
            writes)

    def test_electorates_are_pushed_at_their_uuid(self):
        """They used to be keyed on legacy_id, so one without it could not go."""
        from .firebase import push
        from .models import Electorate

        without = Electorate.objects.create(
            name="New Seat", region="Auckland", valid_from=date(2026, 1, 1))
        writes = []

        def record(db, collection, document_id, payload, dry_run):
            writes.append((collection, str(document_id)))
            return document_id

        with patch.object(push, "get_firestore_client", lambda: object()), \
                patch.object(push, "_write", record):
            count = push.push_persistent_electorates()

        self.assertEqual(count, 1)
        self.assertEqual(writes, [("persistent_electorates", str(without.id))])


# Firestore writes stay OFF here on purpose. Publishing now names the published
# paths on the event document, so a publish in this class with the gate open
# would write to the shared project the service account points at -- which is
# production. The tests that care about that write patch it and assert on it.
@override_settings(ELECTIONS_PUBLISH_ENABLED=True, FIREBASE_PUSH_ENABLED=False,
                   ELECTIONS_SNAPSHOT_DOMAIN="elections-r2.example.nz")
class LiveSyncPublishTests(TestCase):
    """Publishing during a count, once the loop that used to do it is gone.

    Every payload is content addressed, so a publish that does not record its
    path and rewrite the manifest leaves the object unreachable in the bucket
    and the manifest pointing at the previous one. That was a real defect: the
    reference payload was published and its path thrown away.
    """

    @classmethod
    def setUpTestData(cls):
        nz = dt_timezone(timedelta(hours=13))
        cls.election = Election.objects.create(
            name="2026 General Election", polling_date=date(2026, 11, 7),
            polls_close=datetime(2026, 11, 7, 19, 0, tzinfo=nz))
        cls.version = ElectionResultVersion.objects.create(
            election=cls.election, name="Election night", is_primary=True,
            access_mode="firebase", firebase_id="ge2026_prelim", is_live=True)
        ElectionElectorate.objects.create(
            results_version=cls.version, number=1, name="Auckland Central")

    def _publish(self, root, **kwargs):
        """Run a publish pass with the writer pointed at a directory.

        The Firestore client is replaced as well as the storage writer. The
        settings gate above already refuses the write, so this is belt and
        braces -- but the credentials in any environment are the live ones, and
        a publish test must not be one override away from using them.
        """
        from .firebase import ingest
        from .snapshots import publisher

        def no_firestore():
            raise AssertionError("a publish test must not reach Firestore")

        with patch.object(publisher, "StorageWriter",
                          lambda: publisher.LocalWriter(root)), \
                patch("wts_app.firebase.push.get_firestore_client", no_firestore):
            return ingest.refresh_snapshots(self.version, **kwargs)

    def test_publishing_reference_records_its_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._publish(pathlib.Path(tmp), include_reference=True)

        self.version.refresh_from_db()
        self.assertRegex(self.version.snapshot_paths["reference"],
                         r"/reference-[0-9a-f]{12}\.json$")
        self.assertEqual(result["reference"],
                         self.version.snapshot_paths["reference"])

    def test_manifest_names_the_reference_just_published(self):
        """An unreferenced payload is the same as no payload at all."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._publish(root, include_reference=True)
            manifest = json.loads((root / "manifest.json").read_text())

            entry = manifest["elections"][0]["results_versions"][0]
            self.assertEqual(entry["paths"]["reference"],
                             self.version.snapshot_paths["reference"])
            self.assertTrue((root / entry["paths"]["reference"]).exists())

    def test_results_only_pass_leaves_the_reference_path_alone(self):
        """Ending a count republishes results without touching reference data."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._publish(root, include_reference=True)
            reference = self.version.snapshot_paths["reference"]
            self._publish(root)

        self.version.refresh_from_db()
        self.assertEqual(self.version.snapshot_paths["reference"], reference)

    def test_publishing_names_the_paths_on_the_event_document(self):
        """The event document and the manifest must describe the same payloads."""
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wts_app.firebase.push.push_snapshot_paths") as push_paths:
                result = self._publish(pathlib.Path(tmp), include_reference=True)

        self.version.refresh_from_db()
        push_paths.assert_called_once()
        _, pushed = push_paths.call_args[0]
        self.assertEqual(pushed, self.version.snapshot_paths)
        self.assertTrue(result["paths_pushed"])

    def test_paths_are_pushed_on_a_results_only_pass(self):
        """The regression: a publish that imports nothing still has new paths.

        Naming them only on the pass that imported reference data meant a
        version whose reference data was already held could never have its paths
        written at all, and every visitor paid for several hundred Firestore
        reads instead.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._publish(root, include_reference=True)
            with patch("wts_app.firebase.push.push_snapshot_paths") as push_paths:
                self._publish(root)

        push_paths.assert_called_once()
        _, pushed = push_paths.call_args[0]
        self.version.refresh_from_db()
        self.assertEqual(pushed["results"], self.version.snapshot_paths["results"])
        self.assertEqual(pushed["reference"], self.version.snapshot_paths["reference"])

    def test_paths_are_skipped_without_a_firestore_event(self):
        """Nothing to write them to, and nothing that would read them."""
        from .firebase import push

        self.version.firebase_id = None
        with patch("wts_app.firebase.push.push_snapshot_paths") as push_paths:
            self.assertIsNone(push.sync_snapshot_paths(self.version))
        push_paths.assert_not_called()

    def test_a_refused_firestore_write_does_not_fail_the_publish(self):
        """The paths are a cost saving; the manifest still names the same ones."""
        from .firebase import push

        with patch("wts_app.firebase.push.push_snapshot_paths",
                   side_effect=push.FirebasePushDisabled("nope")):
            self.assertIsNone(push.sync_snapshot_paths(self.version, {}))

    def test_a_broken_firestore_write_does_not_fail_the_publish(self):
        """Same reasoning for a write that fails rather than being refused."""
        from .firebase import push

        with patch("wts_app.firebase.push.push_snapshot_paths",
                   side_effect=RuntimeError("firestore unavailable")):
            with self.assertLogs("wts_app.firebase.push", level="WARNING"):
                self.assertIsNone(push.sync_snapshot_paths(self.version, {}))

    def test_the_event_document_carries_the_recorded_paths(self):
        """A routine event push keeps the two in agreement as well."""
        from .firebase import push

        with tempfile.TemporaryDirectory() as tmp:
            self._publish(pathlib.Path(tmp), include_reference=True)

        self.version.refresh_from_db()
        document = push.build_event_document(self.version)
        self.assertEqual(document["paths"], self.version.snapshot_paths)


@override_settings(ELECTIONS_PUBLISH_ENABLED=True)
class ManifestPropagationTests(TestCase):
    """The manifest is the control plane, so it must follow the database.

    Clients never read this database; they read the published manifest. If
    `is_live` changes here and the manifest is not rewritten, the kill switch
    does nothing at all.
    """

    @classmethod
    def setUpTestData(cls):
        nz = dt_timezone(timedelta(hours=13))
        cls.old = Election.objects.create(
            name="2023 General Election", polling_date=date(2023, 10, 14),
            polls_close=datetime(2023, 10, 14, 19, 0, tzinfo=nz))
        cls.old_version = ElectionResultVersion.objects.create(
            election=cls.old, name="Official count", is_primary=True)
        cls.new = Election.objects.create(
            name="2026 General Election", polling_date=date(2026, 5, 16),
            polls_close=datetime(2026, 5, 16, 19, 0, tzinfo=nz))
        cls.new_version = ElectionResultVersion.objects.create(
            election=cls.new, name="Election night", is_primary=True,
            access_mode="firebase", firebase_id="ge2026")

    def test_manifest_only_publish_writes_nothing_else(self):
        """Payloads run to megabytes and must not be regenerated on a save."""
        from .snapshots import publisher

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            publisher.publish_all(publisher.LocalWriter(root))

            writer = publisher.LocalWriter(root)
            publisher.publish_manifest_only(writer)

        self.assertEqual(writer.written, ["manifest.json"])

    def test_manifest_only_publish_describes_every_published_version(self):
        from .snapshots import publisher

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            publisher.publish_all(publisher.LocalWriter(root))
            publisher.publish_manifest_only(publisher.LocalWriter(root))
            manifest = json.loads((root / "manifest.json").read_text())

        slugs = {e["slug"] for e in manifest["elections"]}
        self.assertEqual(slugs, {"2023-general-election", "2026-general-election"})

    def test_manifest_reflects_a_changed_kill_switch(self):
        from .snapshots import publisher

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            publisher.publish_all(publisher.LocalWriter(root))

            ElectionResultVersion.objects.filter(id=self.new_version.id).update(is_live=True)
            publisher.publish_manifest_only(publisher.LocalWriter(root))
            manifest = json.loads((root / "manifest.json").read_text())

        live = {v["firebase_id"]: v["is_live"]
                for e in manifest["elections"] for v in e["results_versions"]}
        self.assertTrue(live["ge2026"])

    def test_a_version_never_published_stays_out_of_the_manifest(self):
        """There would be nothing for the manifest to point at."""
        from .snapshots import publisher

        unpublished = ElectionResultVersion.objects.create(
            election=self.new, name="Preliminary")

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            publisher.publish_all(
                publisher.LocalWriter(root), versions=[self.new_version])
            publisher.publish_manifest_only(publisher.LocalWriter(root))
            manifest = json.loads((root / "manifest.json").read_text())

        slugs = {v["slug"] for e in manifest["elections"] for v in e["results_versions"]}
        self.assertIn(self.new_version.slug, slugs)
        self.assertNotIn(unpublished.slug, slugs)

    def test_saving_a_version_queues_a_manifest_publish(self):
        from .tasks import firebase as firebase_tasks

        with patch.object(firebase_tasks.publish_manifest, "delay") as queued:
            with self.captureOnCommitCallbacks(execute=True):
                self.new_version.description = "Updated on the night"
                self.new_version.save()

        queued.assert_called_once()

    def test_saving_an_election_queues_a_manifest_publish(self):
        from .tasks import firebase as firebase_tasks

        with patch.object(firebase_tasks.publish_manifest, "delay") as queued:
            with self.captureOnCommitCallbacks(execute=True):
                self.new.name = "2026 general election"
                self.new.save()

        queued.assert_called_once()

    def test_a_broker_failure_does_not_break_the_save(self):
        """An admin edit must not fail because Redis is down."""
        from .tasks import firebase as firebase_tasks

        with patch.object(firebase_tasks.publish_manifest, "delay",
                          side_effect=OSError("broker unreachable")):
            with self.captureOnCommitCallbacks(execute=True):
                self.new_version.description = "Saved with no broker"
                self.new_version.save()

        self.new_version.refresh_from_db()
        self.assertEqual(self.new_version.description, "Saved with no broker")


class AdminActionTests(TestCase):
    """The admin actions must do what their labels say."""

    @classmethod
    def setUpTestData(cls):
        cls.a = PersistentParty.objects.create(display_name="Party A", firebase_id="pp_a")
        cls.b = PersistentParty.objects.create(display_name="Party B", firebase_id="pp_b")
        cls.c = PersistentParty.objects.create(display_name="Party C", firebase_id="pp_c")

    def test_pushing_selected_parties_pushes_only_those(self):
        """The action says 'selected'; it must not push every row."""
        from .tasks.firebase import push_persistent

        with override_settings(FIREBASE_PUSH_ENABLED=True):
            with patch("wts_app.firebase.push._write") as write:
                push_persistent(only=["persistent_parties"],
                                ids=[str(self.a.id), str(self.c.id)])

        pushed = {call.args[2] for call in write.call_args_list}
        self.assertEqual(pushed, {"pp_a", "pp_c"})

    def test_pushing_with_no_selection_pushes_everything(self):
        from .tasks.firebase import push_persistent

        with override_settings(FIREBASE_PUSH_ENABLED=True):
            with patch("wts_app.firebase.push._write") as write:
                push_persistent(only=["persistent_parties"])

        self.assertEqual(len(write.call_args_list), 3)


class NameMatchingTests(TestCase):
    """The rules that decide whether two names are the same person.

    Every pair below is real, from the 2023 general election measured against
    the persistent records that existed at the time.
    """

    def test_diacritics_are_folded(self):
        from .matching import names
        self.assertEqual(names.normalise("MĀHUTA, Nanaia"), names.normalise("MAHUTA, Nanaia"))

    def test_added_middle_names_are_the_same_person(self):
        from .matching import names
        self.assertTrue(names.is_structural_match(
            "GREENSLADE, David", "GREENSLADE, David John"))
        self.assertTrue(names.is_structural_match(
            "McDONALD, Don S", "McDONALD, Don S Newt"))

    def test_different_people_are_not_matched(self):
        from .matching import names
        for one, other in (("ANDERSON, Dion", "ANDERSON, Erina"),
                           ("ROBB, James", "CROW, James"),
                           ("GORDON, Christopher", "GREY, Christopher"),
                           ("WILLIAMSON, Myra", "WILLIAMS, Ema")):
            self.assertFalse(names.is_structural_match(one, other), f"{one} ~ {other}")

    def test_nicknames_are_left_to_a_person(self):
        """Probably the same person, but not mechanically decidable."""
        from .matching import names
        self.assertFalse(names.is_structural_match(
            "LAUDERDALE, Kathleen", "LAUDERDALE, Kath"))
        self.assertFalse(names.is_structural_match("GIELEN, Jacobus", "GIELEN, Jack"))

    def test_a_given_name_prefix_is_token_wise_not_character_wise(self):
        """A character prefix would wrongly match Jo to John."""
        from .matching import names
        self.assertFalse(names.is_structural_match("SMITH, Jo", "SMITH, John"))

    def test_a_false_pair_can_outscore_a_true_one(self):
        """The reason similarity never decides a link."""
        from .matching import names
        false_pair = names.similarity("JOHNSTON, Brian", "JOHNSON, Ian")
        true_pair = names.similarity("GREENSLADE, David", "GREENSLADE, David John")
        self.assertGreater(false_pair, true_pair)


class DistanceMatchingTests(TestCase):
    """Voting places move a few metres between elections, so they match on
    proximity rather than address text."""

    def test_threshold_matches_the_results_worker(self):
        from .matching import geo
        self.assertEqual(geo.DEFAULT_THRESHOLD_METRES, 50)

    def test_distance_is_accurate_enough_for_a_fifty_metre_threshold(self):
        from .matching import geo
        # Two points 100 m apart in latitude at Wellington's latitude.
        metres = geo.distance_metres((-41.2865, 174.7762), (-41.28560, 174.7762))
        self.assertAlmostEqual(metres, 100, delta=1)

    def test_missing_coordinates_are_not_a_match(self):
        from .matching import geo
        self.assertIsNone(geo.distance_metres((None, None), (-41.28, 174.77)))


class PersistentMatchingTests(TestCase):
    """End to end over the four entity types."""

    @classmethod
    def setUpTestData(cls):
        nz = dt_timezone(timedelta(hours=13))
        cls.election = Election.objects.create(
            name="2026 General Election", polling_date=date(2026, 5, 16),
            polls_close=datetime(2026, 5, 16, 19, 0, tzinfo=nz))
        cls.version = ElectionResultVersion.objects.create(
            election=cls.election, name="Election night", is_primary=True)

        cls.returning = PersistentCandidate.objects.create(display_name="GREENSLADE, David John")
        cls.party = PersistentParty.objects.create(
            display_name="Green Party", abbreviation="GRN")

        cls.electorate = ElectionElectorate.objects.create(
            results_version=cls.version, number=1, name="Auckland Central")
        cls.election_party = ElectionParty.objects.create(
            results_version=cls.version, number=5, name="Green Party", abbreviation="GRN")

    def _candidate(self, name, number):
        return ElectionCandidate.objects.create(
            results_version=self.version, number=number, name=name,
            electorate=self.electorate, party=self.election_party)

    def test_a_returning_candidate_is_linked_by_the_structural_rule(self):
        from .matching.matchers import STRUCTURAL, CandidateMatcher

        candidate = self._candidate("GREENSLADE, David", 1)
        matcher = CandidateMatcher(self.version)
        outcome = matcher.classify(candidate)

        self.assertEqual(outcome.kind, STRUCTURAL)
        self.assertEqual(outcome.suggestion.persistent, self.returning)

    def test_a_new_candidate_is_marked_for_creation(self):
        from .matching.matchers import CREATE, CandidateMatcher

        candidate = self._candidate("TOTALLY, Unrelated Person", 2)
        self.assertEqual(CandidateMatcher(self.version).classify(candidate).kind, CREATE)

    def test_min_score_cannot_prevent_a_link(self):
        """The bug this design exists to avoid.

        Raising the threshold must not stop a structural match being linked --
        the two must be independent.
        """
        from .matching.matchers import STRUCTURAL, CandidateMatcher

        candidate = self._candidate("GREENSLADE, David", 3)
        for min_score in (0.80, 0.95, 0.99):
            outcome = CandidateMatcher(self.version, min_score=min_score).classify(candidate)
            self.assertEqual(outcome.kind, STRUCTURAL, f'at min_score={min_score}')

    def test_min_score_moves_only_the_review_boundary(self):
        from .matching.matchers import CREATE, REVIEW, CandidateMatcher

        candidate = self._candidate("GREENSLADE, Davos", 4)
        self.assertEqual(CandidateMatcher(self.version, min_score=0.80)
                         .classify(candidate).kind, REVIEW)
        self.assertEqual(CandidateMatcher(self.version, min_score=0.99)
                         .classify(candidate).kind, CREATE)

    def test_a_party_matches_on_its_abbreviation(self):
        from .matching.matchers import EXACT, PartyMatcher

        outcome = PartyMatcher(self.version).classify(self.election_party)
        self.assertEqual(outcome.kind, EXACT)
        self.assertEqual(outcome.suggestion.persistent, self.party)

    def test_a_voting_place_matches_the_same_hall_a_few_metres_away(self):
        from .matching.matchers import EXACT, VotingPlaceMatcher

        PersistentVotingPlace.objects.create(
            address="Ponsonby Community Centre", latitude=-36.85000, longitude=174.74000)
        place = ElectionVotingPlace.objects.create(
            results_version=self.version, number=1, physical_electorate=self.electorate,
            address="Ponsonby Community Ctr", latitude=-36.85010, longitude=174.74000)

        outcome = VotingPlaceMatcher(self.version).classify(place)
        self.assertEqual(outcome.kind, EXACT)

    def test_a_distant_voting_place_is_a_new_record(self):
        from .matching.matchers import CREATE, VotingPlaceMatcher

        PersistentVotingPlace.objects.create(
            address="Ponsonby Community Centre", latitude=-36.85000, longitude=174.74000)
        place = ElectionVotingPlace.objects.create(
            results_version=self.version, number=2, physical_electorate=self.electorate,
            address="Somewhere else", latitude=-36.90000, longitude=174.74000)

        self.assertEqual(VotingPlaceMatcher(self.version).classify(place).kind, CREATE)

    def test_electorates_are_never_created_automatically(self):
        """They carry boundaries, regions and slugs a results feed cannot supply."""
        from .matching.matchers import ElectorateMatcher

        matcher = ElectorateMatcher(self.version)
        self.assertFalse(matcher.can_create)
        with self.assertRaises(NotImplementedError):
            matcher.create_persistent(self.electorate)


class PublishGateTests(TestCase):
    """Every environment holds the same R2 credentials, so the credentials are
    no protection. The gate is."""

    def test_writing_to_r2_is_refused_unless_the_environment_allows_it(self):
        from .snapshots import publisher

        with override_settings(ELECTIONS_PUBLISH_ENABLED=False):
            with self.assertRaises(publisher.PublishDisabled):
                publisher.StorageWriter()

    def test_local_and_dry_run_are_never_gated(self):
        import tempfile
        from .snapshots import publisher

        with override_settings(ELECTIONS_PUBLISH_ENABLED=False):
            publisher.DryRunWriter()
            with tempfile.TemporaryDirectory() as tmp:
                publisher.LocalWriter(tmp)

    def test_saving_a_version_does_not_queue_a_publish_when_disabled(self):
        """The bug that overwrote a live manifest from a test database."""
        from datetime import datetime, timedelta, timezone as dt_tz
        from .tasks import firebase as firebase_tasks

        nz = dt_tz(timedelta(hours=13))
        election = Election.objects.create(
            name="Gate Test Election", polling_date=date(2026, 5, 16),
            polls_close=datetime(2026, 5, 16, 19, 0, tzinfo=nz))

        with override_settings(ELECTIONS_PUBLISH_ENABLED=False):
            with patch.object(firebase_tasks.publish_manifest, "delay") as queued:
                with self.captureOnCommitCallbacks(execute=True):
                    ElectionResultVersion.objects.create(
                        election=election, name="Election night")
        queued.assert_not_called()

    def test_saving_a_version_queues_a_publish_when_enabled(self):
        from datetime import datetime, timedelta, timezone as dt_tz
        from .tasks import firebase as firebase_tasks

        nz = dt_tz(timedelta(hours=13))
        election = Election.objects.create(
            name="Gate Test Election Two", polling_date=date(2026, 5, 16),
            polls_close=datetime(2026, 5, 16, 19, 0, tzinfo=nz))

        with override_settings(ELECTIONS_PUBLISH_ENABLED=True):
            with patch.object(firebase_tasks.publish_manifest, "delay") as queued:
                with self.captureOnCommitCallbacks(execute=True):
                    ElectionResultVersion.objects.create(
                        election=election, name="Election night")
        queued.assert_called()


class IncumbencyFixture(TestCase):
    """Shared setup: one election with two versions and three seats.

    Three electorates, chosen to cover the three cases the client has to tell
    apart -- a member standing again, a party standing somebody else, and a
    member who left their party -- plus the seat counts that go with them.
    """

    @classmethod
    def setUpTestData(cls):
        from .models.electorates import Electorate

        nz = dt_timezone(timedelta(hours=13))
        cls.election = Election.objects.create(
            name="2026 General Election", polling_date=date(2026, 10, 17),
            polls_close=datetime(2026, 10, 17, 19, 0, tzinfo=nz))
        cls.source = ElectionResultVersion.objects.create(
            election=cls.election, name="Election night", is_primary=True,
            firebase_id="ge2026_night")
        cls.target = ElectionResultVersion.objects.create(
            election=cls.election, name="Official count",
            firebase_id="ge2026_official")

        cls.blue = PersistentParty.objects.create(
            display_name="Blue Party", abbreviation="BLU", firebase_id="pp_blue")
        cls.red = PersistentParty.objects.create(
            display_name="Red Party", abbreviation="RED", firebase_id="pp_red")

        cls.ilam = Electorate.objects.create(
            name="Ilam", region="Canterbury", valid_from=date(2020, 1, 1))
        cls.epsom = Electorate.objects.create(
            name="Epsom", region="Auckland", valid_from=date(2020, 1, 1))
        cls.rongotai = Electorate.objects.create(
            name="Rongotai", region="Wellington", valid_from=date(2020, 1, 1))

        cls.sitting = PersistentCandidate.objects.create(display_name="HOLD, Hannah")
        cls.retiring = PersistentCandidate.objects.create(display_name="GOING, Gerald")
        cls.defector = PersistentCandidate.objects.create(display_name="CROSS, Carla")

        # Standing again for the party that won the seat.
        cls.held = ElectorateIncumbent.objects.create(
            results_version=cls.source, electorate=cls.ilam,
            persistent_candidate=cls.sitting, persistent_party=cls.blue)
        # Won for Blue, now sits for Red.
        cls.moved = ElectorateIncumbent.objects.create(
            results_version=cls.source, electorate=cls.epsom,
            persistent_candidate=cls.defector, persistent_party=cls.blue,
            has_left_party=True, current_persistent_party=cls.red)
        # Red-held; the member is standing down, so Red stands somebody else.
        cls.standing_down = ElectorateIncumbent.objects.create(
            results_version=cls.source, electorate=cls.rongotai,
            persistent_candidate=cls.retiring, persistent_party=cls.red)

        cls.blue_seats = PartyIncumbent.objects.create(
            results_version=cls.source, persistent_party=cls.blue,
            electorate_seats=1, list_seats=4)
        # Deliberately a different total from Blue's five, so the manifest's
        # ordering by seats held is tested rather than a tie-break on id.
        cls.red_seats = PartyIncumbent.objects.create(
            results_version=cls.source, persistent_party=cls.red,
            electorate_seats=2, list_seats=4)

    @staticmethod
    def publish(version=None):
        """Publish locally and return the parsed manifest.

        ``record=False`` so a test does not leave published paths behind; the
        versions written on this run are still described, because publish_all
        passes their fresh paths through.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            writer = publisher.LocalWriter(root)
            publisher.publish_all(
                writer, versions=[version] if version else None, record=False)
            return json.loads((root / "manifest.json").read_text())


class IncumbencyModelTests(IncumbencyFixture):
    """What the two tables will and will not accept."""

    def test_one_incumbent_per_electorate_per_version(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            ElectorateIncumbent.objects.create(
                results_version=self.source, electorate=self.ilam,
                persistent_party=self.red)

    def test_the_same_electorate_can_be_held_in_two_versions(self):
        """Incumbency is per version, so copying forward must not collide."""
        ElectorateIncumbent.objects.create(
            results_version=self.target, electorate=self.ilam,
            persistent_candidate=self.sitting, persistent_party=self.blue)
        self.assertEqual(
            ElectorateIncumbent.objects.filter(electorate=self.ilam).count(), 2)

    def test_total_seats_adds_the_two_counts(self):
        self.assertEqual(self.blue_seats.total_seats, 5)
        self.assertEqual(self.red_seats.total_seats, 6)

    def test_one_party_incumbent_per_party_per_version(self):
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            PartyIncumbent.objects.create(
                results_version=self.source, persistent_party=self.blue,
                electorate_seats=9)

    def test_sitting_party_follows_a_defection(self):
        """Seat counts go by where a member sits now, not what they were elected for."""
        self.assertEqual(self.held.sitting_persistent_party_id, self.blue.id)
        self.assertEqual(self.moved.sitting_persistent_party_id, self.red.id)

    def test_a_member_who_left_for_no_party_sits_as_an_independent(self):
        independent = ElectorateIncumbent(
            results_version=self.target, electorate=self.ilam,
            persistent_candidate=self.sitting, persistent_party=self.blue,
            has_left_party=True)
        independent.full_clean()
        self.assertIsNone(independent.sitting_persistent_party_id)

    def test_a_defection_to_the_same_party_is_rejected(self):
        from django.core.exceptions import ValidationError

        incumbent = ElectorateIncumbent(
            results_version=self.target, electorate=self.ilam,
            persistent_party=self.blue, has_left_party=True,
            current_persistent_party=self.blue)
        with self.assertRaises(ValidationError) as caught:
            incumbent.clean()
        self.assertIn("current_persistent_party", caught.exception.message_dict)

    def test_a_current_party_without_a_defection_is_rejected(self):
        from django.core.exceptions import ValidationError

        incumbent = ElectorateIncumbent(
            results_version=self.target, electorate=self.ilam,
            persistent_party=self.blue, current_persistent_party=self.red)
        with self.assertRaises(ValidationError) as caught:
            incumbent.clean()
        self.assertIn("has_left_party", caught.exception.message_dict)

    def test_a_party_cannot_sit_in_both_blocs(self):
        from django.core.exceptions import ValidationError

        self.source.bloc_order_left = [str(self.blue.id)]
        self.source.bloc_order_right = [str(self.blue.id)]
        with self.assertRaises(ValidationError) as caught:
            self.source.clean()
        self.assertIn("bloc_order_right", caught.exception.message_dict)


class IncumbencyManifestTests(IncumbencyFixture):
    """Incumbency and blocs ride in the manifest rather than in a payload.

    They are curated descriptions of an event, not results, so they must reach
    a client on a save with nothing published. The manifest is also the one
    object every visitor fetches, so what is *not* written matters as much.
    """

    def entry(self, manifest, slug):
        versions = manifest["elections"][0]["results_versions"]
        return next(v for v in versions if v["slug"] == slug)

    def test_manifest_carries_incumbents_as_persistent_ids(self):
        entry = self.entry(self.publish(), "election-night")
        electorates = entry["incumbency"]["electorates"]

        # Alphabetical by electorate, so the file is readable and stable.
        self.assertEqual([row["electorate"] for row in electorates],
                         [str(self.epsom.id), str(self.ilam.id),
                          str(self.rongotai.id)])
        ilam = next(row for row in electorates
                    if row["electorate"] == str(self.ilam.id))
        self.assertEqual(ilam["candidate"], str(self.sitting.id))
        self.assertEqual(ilam["party"], str(self.blue.id))

    def test_manifest_names_persistent_objects_rather_than_repeating_them(self):
        """The client already holds every persistent object."""
        ilam = next(row for row in
                    self.entry(self.publish(), "election-night")["incumbency"]["electorates"]
                    if row["electorate"] == str(self.ilam.id))
        self.assertEqual(set(ilam), {"electorate", "candidate", "party"})
        self.assertNotIn("Ilam", json.dumps(ilam))

    def test_manifest_carries_party_seats_to_compare_against(self):
        parties = self.entry(self.publish(), "election-night")["incumbency"]["parties"]
        # Red leads on six seats held to Blue's five.
        self.assertEqual(parties, [
            {"party": str(self.red.id), "electorate_seats": 2, "list_seats": 4},
            {"party": str(self.blue.id), "electorate_seats": 1, "list_seats": 4},
        ])

    def test_manifest_carries_a_defection(self):
        epsom = next(row for row in
                     self.entry(self.publish(), "election-night")["incumbency"]["electorates"]
                     if row["electorate"] == str(self.epsom.id))
        self.assertTrue(epsom["left_party"])
        self.assertEqual(epsom["party"], str(self.blue.id))
        self.assertEqual(epsom["current_party"], str(self.red.id))

    def test_a_vacant_seat_names_no_candidate(self):
        self.held.persistent_candidate = None
        self.held.save()
        ilam = next(row for row in
                    self.entry(self.publish(), "election-night")["incumbency"]["electorates"]
                    if row["electorate"] == str(self.ilam.id))
        self.assertNotIn("candidate", ilam)

    def test_false_members_are_left_out(self):
        """Nothing every visitor fetches should carry a field saying nothing."""
        ilam = next(row for row in
                    self.entry(self.publish(), "election-night")["incumbency"]["electorates"]
                    if row["electorate"] == str(self.ilam.id))
        self.assertNotIn("left_party", ilam)
        self.assertNotIn("current_party", ilam)

    def test_manifest_omits_incumbency_where_none_is_curated(self):
        entry = self.entry(self.publish(), "official-count")
        self.assertNotIn("incumbency", entry)
        self.assertNotIn("blocs", entry)

    def test_manifest_carries_the_bloc_order(self):
        self.source.bloc_order_left = [str(self.red.id)]
        self.source.bloc_order_right = [str(self.blue.id)]
        self.source.save()

        entry = self.entry(self.publish(), "election-night")
        self.assertEqual(entry["blocs"],
                         {"left": [str(self.red.id)], "right": [str(self.blue.id)]})

    def test_one_curated_bloc_is_enough_to_publish_the_key(self):
        self.source.bloc_order_left = [str(self.red.id)]
        self.source.save()
        entry = self.entry(self.publish(), "election-night")
        self.assertEqual(entry["blocs"], {"left": [str(self.red.id)], "right": []})

    def test_a_new_incumbent_reaches_the_manifest_without_republishing_payloads(self):
        """The point of carrying this in the manifest rather than a payload."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            # Publish properly first, so both versions have recorded paths and
            # so appear in a manifest rebuilt from them.
            publisher.publish_all(publisher.LocalWriter(root))

            ElectorateIncumbent.objects.create(
                results_version=self.target, electorate=self.ilam,
                persistent_candidate=self.sitting, persistent_party=self.blue)

            writer = publisher.LocalWriter(root)
            publisher.publish_manifest_only(writer)
            # Nothing else was rewritten: no payload changed, and none had to.
            self.assertEqual(writer.written, ["manifest.json"])

            manifest = json.loads((root / "manifest.json").read_text())

        entry = self.entry(manifest, "official-count")
        self.assertEqual(entry["incumbency"]["electorates"],
                         [{"electorate": str(self.ilam.id),
                           "candidate": str(self.sitting.id),
                           "party": str(self.blue.id)}])

    def test_building_the_manifest_does_not_query_per_version(self):
        """Guards the prefetch: this runs on every save of a version.

        One query for the versions and one for each kind of incumbency, however
        many versions there are. Without the prefetch it would be two more per
        version, on a rebuild that happens on every save.
        """
        with tempfile.TemporaryDirectory() as tmp:
            # A DryRunWriter never records paths, and a version with none is
            # left out of the manifest -- which would make this pass trivially.
            publisher.publish_all(publisher.LocalWriter(pathlib.Path(tmp)))

            with self.assertNumQueries(3):
                entries = publisher.build_manifest_entries()
            self.assertEqual(sum(len(v) for v in entries.values()), 2)

            third = ElectionResultVersion.objects.create(
                election=self.election, name="Recount",
                firebase_id="ge2026_recount")
            ElectorateIncumbent.objects.create(
                results_version=third, electorate=self.ilam,
                persistent_candidate=self.sitting, persistent_party=self.blue)
            PartyIncumbent.objects.create(
                results_version=third, persistent_party=self.blue,
                electorate_seats=1)
            publisher.publish_all(
                publisher.LocalWriter(pathlib.Path(tmp)), versions=[third])

            # A third published version, carrying incumbency of its own, and
            # still three queries.
            with self.assertNumQueries(3):
                entries = publisher.build_manifest_entries()
            self.assertEqual(sum(len(v) for v in entries.values()), 3)


class CopyIncumbentsTests(IncumbencyFixture):
    """Moving curation to a duplicate version rather than entering it twice."""

    def run_command(self, *args):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command('copy_incumbents', '--from', 'election-night',
                     '--to', 'official-count', *args, stdout=out)
        return out.getvalue()

    def target_electorates(self):
        return set(ElectorateIncumbent.objects.filter(
            results_version=self.target).values_list('electorate_id', flat=True))

    def test_dry_run_reports_and_writes_nothing(self):
        output = self.run_command()
        self.assertIn("Nothing was changed", output)
        self.assertIn("3", output)
        self.assertEqual(self.target_electorates(), set())

    def test_apply_copies_both_kinds(self):
        self.run_command('--apply')
        self.assertEqual(
            self.target_electorates(),
            {self.ilam.id, self.epsom.id, self.rongotai.id})
        self.assertEqual(
            PartyIncumbent.objects.filter(results_version=self.target).count(), 2)

    def test_a_defection_travels_with_the_row(self):
        self.run_command('--apply')
        copied = ElectorateIncumbent.objects.get(
            results_version=self.target, electorate=self.epsom)
        self.assertTrue(copied.has_left_party)
        self.assertEqual(copied.current_persistent_party_id, self.red.id)

    def test_seat_counts_travel_with_the_row(self):
        self.run_command('--apply')
        copied = PartyIncumbent.objects.get(
            results_version=self.target, persistent_party=self.blue)
        self.assertEqual((copied.electorate_seats, copied.list_seats), (1, 4))

    def test_running_twice_changes_nothing(self):
        self.run_command('--apply')
        output = self.run_command('--apply')
        self.assertIn("already the same", output)
        self.assertEqual(
            ElectorateIncumbent.objects.filter(results_version=self.target).count(), 3)

    def test_a_differing_row_needs_overwrite(self):
        ElectorateIncumbent.objects.create(
            results_version=self.target, electorate=self.ilam,
            persistent_candidate=self.retiring, persistent_party=self.red)

        output = self.run_command('--apply')
        self.assertIn("already curated differently", output)
        kept = ElectorateIncumbent.objects.get(
            results_version=self.target, electorate=self.ilam)
        self.assertEqual(kept.persistent_party_id, self.red.id)

        self.run_command('--apply', '--overwrite')
        replaced = ElectorateIncumbent.objects.get(
            results_version=self.target, electorate=self.ilam)
        self.assertEqual(replaced.persistent_party_id, self.blue.id)
        self.assertEqual(replaced.persistent_candidate_id, self.sitting.id)

    def test_only_narrows_what_is_copied(self):
        self.run_command('--apply', '--only', 'parties')
        self.assertEqual(self.target_electorates(), set())
        self.assertEqual(
            PartyIncumbent.objects.filter(results_version=self.target).count(), 2)

    def test_an_unknown_only_is_refused(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command('--only', 'voting-places')

    def test_the_same_version_is_refused(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO

        with self.assertRaises(CommandError):
            call_command('copy_incumbents', '--from', 'election-night',
                         '--to', 'election-night', stdout=StringIO())

    def test_different_elections_are_refused(self):
        """A version's incumbents are the previous election's winners."""
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from io import StringIO

        nz = dt_timezone(timedelta(hours=13))
        other = Election.objects.create(
            name="2023 General Election", polling_date=date(2023, 10, 14),
            polls_close=datetime(2023, 10, 14, 19, 0, tzinfo=nz))
        ElectionResultVersion.objects.create(
            election=other, name="Final", firebase_id="ge2023_final")

        with self.assertRaises(CommandError) as caught:
            call_command('copy_incumbents', '--from', 'election-night',
                         '--to', 'final', stdout=StringIO())
        self.assertIn("out of date", str(caught.exception))

    def test_a_seat_count_disagreement_is_reported(self):
        """Blue holds one electorate; saying it holds three should be noticed."""
        self.blue_seats.electorate_seats = 3
        self.blue_seats.save()

        output = self.run_command('--apply')
        self.assertIn("curated 3, counted 1", output)

    def test_counts_that_agree_are_not_reported(self):
        """Red won two seats but one member crossed to it, so two is right."""
        output = self.run_command('--apply')
        self.assertNotIn("counted", output)
