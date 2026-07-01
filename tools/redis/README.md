# Redis Test Service

Disposable Redis service for backend integration tests.

Run from the repository root:

```powershell
./scripts/test-backend-redis.ps1
```

The script starts this Compose service, sets
`BAB_TEST_REDIS_URL=redis://127.0.0.1:16379/15`, flushes DB 15 before and after the
focused Redis tests, and removes the container by default. The container still listens
on Redis port 6379 internally; 16379 is the default host port to avoid colliding with
developer Redis instances. No persistent volumes are used.
