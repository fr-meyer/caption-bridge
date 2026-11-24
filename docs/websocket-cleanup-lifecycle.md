# WebSocket cleanup under host cancellation

The endpoint owns its reader, writer, failure supervisor and connection-scoped
catalogue refresh/renewal tasks. On disconnect it synchronously removes the
listener, releases connection ownership and applies the existing disconnect/TTS
effects before awaiting task cleanup. A new owner admitted during cleanup must
not be affected by the old connection.

Reader EOF and ASGI host cancel-scope shutdown can overlap at the final
`asyncio.gather(..., return_exceptions=True)`. The endpoint has already cancelled
its children at that point. Cancellation of the join can re-cancel those children
and propagate a child’s untagged `CancelledError` through the join. AnyIO treats
that as foreign cancellation, not its own scoped shutdown; a synchronous ASGI
client can then observe a cancelled application future at context exit.
`return_exceptions=True` does not protect a gather that is itself cancelled.

Only the owned-task join is shielded with AnyIO’s cancel scope. Children are
still explicitly cancelled and awaited; cleanup is not detached or declared
complete early. The endpoint’s existing handler-cancellation branch still
re-raises genuine cancellation after cleanup. There is no new timeout, retry,
exception suppression, client/backend replacement or changed catalogue policy.
The supported AnyIO API is already present in the locked FastAPI/Starlette
dependency graph.

`tests/unit/test_websocket_cleanup_lifecycle.py` deterministically schedules host
cancellation after reader EOF and synchronous owner release, at the owned-task
join. It covers both immediate and cooperative asynchronous writer cleanup,
checks all pending owner children are joined, and verifies external endpoint
cancellation retains its reason and is not swallowed. An additional controlled
real TestClient case reproduces the synchronous future-cancellation failure at
context exit without changing the transport/backend. The existing
`tests/unit/test_translation_catalogue_ws.py` runs unchanged through the real
FastAPI/Starlette TestClient, including cancelled metadata fetches and TTL
renewal failure-state publication. Ownership, epoch, selected-output,
backpressure and readiness tests remain authoritative. These are software
lifecycle tests, not provider, account, acoustic or human acceptance.
