# Production Deployment Notes

This document describes what changes for a production deployment versus the
local/dev setup. For local development, Redis and Docker are **not required** —
the backend uses an in-process, in-memory session store (see
[backend/main.py](backend/main.py)'s `SessionManager`). Sessions are lost on
process restart in this mode, which is fine for local testing but not for
production.

## Docker / Redis

`docker-compose.yml` has been removed from the repo since local development
doesn't need Docker or Redis. To bring Redis back for a production deployment,
recreate a compose file with a Redis service, e.g.:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - finance-assistant

volumes:
  redis_data:

networks:
  finance-assistant:
    driver: bridge
```

To run it: `docker compose up -d redis`.

### Restoring the Redis-backed SessionManager

The in-memory `SessionManager` in [backend/main.py](backend/main.py) has the
same public interface (`create_session`, `get_session`, `add_turn`,
`get_context`, `get_last_export_filename`) as the previous Redis-backed
version. To switch back to Redis for production:

1. Uncomment `redis==5.0.0` in [backend/requirements.txt](backend/requirements.txt) and `pip install`.
2. Re-add `import redis` and the `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` env vars.
3. Replace the in-memory `_sessions` dict in `SessionManager` with Redis
   `hset` / `hgetall` / `expire` calls, keyed by `session:{session_id}`, storing
   `messages` as a JSON string (this is exactly how the class worked before
   this change — see git history for the original implementation).
4. Construct the client and pass it into `SessionManager(redis_client)`:

```python
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=int(os.getenv("REDIS_DB", 0)),
    decode_responses=True,
)
redis_client.ping()
session_manager = SessionManager(redis_client)
```

5. Set `REDIS_HOST` (e.g. the `redis` service name from `docker-compose.yml`)
   in the backend's environment.

### Why Redis in production

- **Multi-instance deployments**: an in-memory store is per-process, so it
  breaks session continuity if the backend runs behind a load balancer with
  multiple replicas, or restarts/redeploys.
- **Persistence**: Redis with `--appendonly yes` survives container restarts;
  the in-memory store does not.
- **Session expiry**: Redis handles TTL/eviction natively (`EXPIRE`), which is
  more robust than the manual timestamp check used in the in-memory version.

## Other production considerations

- Set a restricted `allow_origins` list in the CORS middleware in
  [backend/main.py](backend/main.py) instead of `["*"]`.
- Run the FastAPI app with a production ASGI server config (multiple `uvicorn`
  workers or behind `gunicorn`), rather than the dev `uvicorn --reload` flow.
- Point `REDIS_HOST`/`REDIS_PORT` at a managed or containerized Redis instance
  reachable from all backend replicas.
