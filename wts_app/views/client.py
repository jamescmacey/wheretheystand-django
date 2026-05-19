import random

from django.db.models import Q
from rest_framework import views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ..models import Bill, Electorate, Party, Person, Vote

HOMEPAGE_LIMIT = 5


def _reading_ordinal(reading):
    if not reading:
        return "Unknown"
    suffix = (
        "th"
        if 11 <= (reading % 100) <= 13
        else {1: "st", 2: "nd", 3: "rd"}.get(reading % 10, "th")
    )
    return f"{reading}{suffix}"


def _vote_display_name(vote):
    return f"{vote.bill.name}, {_reading_ordinal(vote.reading)} reading"


def _with_slug(queryset):
    return queryset.exclude(Q(slug__isnull=True) | Q(slug=""))


def _random_client_path():
    """
    Pick a random public page path (people, electorates, parties, bills, votes).
    Entity type is chosen uniformly among types that have at least one record.
    """
    pools = []

    people = _with_slug(
        Person.objects.filter(parliamentaryaffiliation__isnull=False).distinct()
    )
    if people.exists():
        pools.append(("people", people))

    electorates = _with_slug(Electorate.objects.all())
    if electorates.exists():
        pools.append(("electorates", electorates))

    parties = _with_slug(
        Party.objects.filter(partyaffiliation__isnull=False).distinct()
    )
    if parties.exists():
        pools.append(("parties", parties))

    bills = Bill.objects.all()
    if bills.exists():
        pools.append(("bills", bills))

    votes = Vote.objects.all()
    if votes.exists():
        pools.append(("votes", votes))

    if not pools:
        return None

    entity_type, queryset = random.choice(pools)

    if entity_type in ("people", "electorates", "parties"):
        slug = queryset.order_by("?").values_list("slug", flat=True).first()
        return f"/{entity_type}/{slug}"

    pk = queryset.order_by("?").values_list("id", flat=True).first()
    return f"/{entity_type}/{pk}"


class HomepageView(views.APIView):
    """Recent votes and bills for the site homepage."""

    permission_classes = [AllowAny]

    def get(self, request):


        votes = (
            Vote.objects.select_related("bill")
            .order_by("-date", "-id")[:HOMEPAGE_LIMIT]
        )
        bills = Bill.objects.order_by("-last_activity_date", "-updated_at")[:HOMEPAGE_LIMIT]

        return Response(
            {
                "votes": [
                    {
                        "id": vote.id,
                        "name": _vote_display_name(vote),
                        "date": vote.date,
                    }
                    for vote in votes
                ],
                "bills": [
                    {
                        "id": bill.id,
                        "name": bill.name,
                    }
                    for bill in bills
                ],
            }
        )


class RandomPageView(views.APIView):
    """Return a random client-side route for the homepage “random page” link."""

    permission_classes = [AllowAny]

    def get(self, request):
        path = _random_client_path()
        if path is None:
            return Response({"detail": "No pages available."}, status=503)

        response = Response({"to": path})
        response["Cache-Control"] = "no-store"
        return response
