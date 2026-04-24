"""
Shared resilience primitives: HTTP retries, async helpers, bounded caches,
request-scoped logging context.

Every data client and route should build on these. Do not reinvent them
per-module — that's how stability bugs compound.
"""
