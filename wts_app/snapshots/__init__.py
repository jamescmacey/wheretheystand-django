"""Static election results snapshots published to R2.

Django is the source of truth for election results, but it does not serve them
to the public. On election night the site can expect far more traffic than the
API should carry, so the client reads static JSON from R2 instead, cached at the
edge. This package renders that JSON and uploads it.

The payloads are byte-for-byte what the API returns, because they come from the
same serializers. That is deliberate: pointing the client at a local Django
instance during development exercises the same shape as production.
"""
