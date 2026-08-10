"""Match election entities to the persistent records that outlive them.

The Electoral Commission numbers candidates, parties, electorates and voting
places per election, and reuses those numbers between elections. Persistent
records are what let the site follow the same person or party across elections,
so every election entity needs linking to one -- or a new one creating.

The worker matches what it can during ingest. This package covers the rest.
"""
