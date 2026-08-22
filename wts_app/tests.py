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
    ElectionCandidate, ElectionVotingPlace, ResultsSet, Result, PersistentParty,
    PersistentCandidate, PersistentVotingPlace,
)
from .snapshots import publisher


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

            reference = json.loads((root / entry["paths"]["reference"]).read_text())
            self.assertEqual(reference["candidates"][0]["party"], 5)
            self.assertEqual(reference["voting_places"], [])

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
            coalition_order_left=[str(cls.left.id), str(cls.right.id)],
            comparison_version_ids=[str(cls.earlier.id)])

    def test_event_document_carries_curated_fields(self):
        from .firebase import push

        document = push.build_event_document(self.version)
        self.assertEqual(document["name"], "Official count")
        self.assertTrue(document["is_live"])
        # Django spells this with a hyphen; the Firestore enum does not.
        self.assertEqual(document["election_type"], "by_election")
        # Ordered UUID lists resolve to the ids Firestore uses.
        self.assertEqual(document["coalition_order_left"], ["pp_left", "pp_right"])
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

        self.version.coalition_order_right = ["4b1f4c3e-0000-0000-0000-000000000000"]
        with self.assertRaises(ValidationError) as caught:
            self.version.clean()
        self.assertIn("coalition_order_right", caught.exception.message_dict)


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


@override_settings(ELECTIONS_PUBLISH_ENABLED=True, FIREBASE_PUSH_ENABLED=True,
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
        """Run a publish pass with the writer pointed at a directory."""
        from .firebase import ingest
        from .snapshots import publisher

        with patch.object(publisher, "StorageWriter",
                          lambda: publisher.LocalWriter(root)):
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

    def test_refdata_url_points_at_the_published_reference(self):
        from .firebase import ingest

        with patch("wts_app.firebase.push.push_refdata_url") as push_url:
            url = ingest.publish_refdata_url(
                self.version, "events/2026-general-election/night/reference-abc123def456.json")

        self.assertEqual(
            url,
            "https://elections-r2.example.nz/events/2026-general-election/"
            "night/reference-abc123def456.json")
        push_url.assert_called_once()

    def test_refdata_url_is_skipped_without_a_firestore_event(self):
        """Nothing to write it to, and nothing that would read it."""
        from .firebase import ingest

        self.version.firebase_id = None
        with patch("wts_app.firebase.push.push_refdata_url") as push_url:
            self.assertIsNone(
                ingest.publish_refdata_url(self.version, "reference-abc123def456.json"))
        push_url.assert_not_called()

    def test_a_refused_firestore_write_does_not_fail_the_publish(self):
        """refdata_url is a cost saving; the dashboard renders without it."""
        from .firebase import ingest, push

        with patch("wts_app.firebase.push.push_refdata_url",
                   side_effect=push.FirebasePushDisabled("nope")):
            self.assertIsNone(
                ingest.publish_refdata_url(self.version, "reference-abc123def456.json"))


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
