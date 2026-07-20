# Tests

These tests exercise the extension's backend (manifest shape, workflow store,
host service, run sync, jobs, events bridge, blueprint routes) but need the
**panel's Flask app and pytest fixtures** (`app`, `client`, `auth_headers`), so
they run from inside a ServerKit checkout rather than standalone:

```bash
# Symlink (or copy) this file into the panel's test suite:
ln -s "$(pwd)/test_tramo_extension.py" /path/to/ServerKit/backend/tests/

# Then run it from the panel backend:
cd /path/to/ServerKit/backend
pytest tests/test_tramo_extension.py
```

Via symlink the test resolves this repo's root with `os.path.realpath`; if you
copy the file instead, point it at the repo:

```bash
SERVERKIT_TRAMO_DIR=/path/to/serverkit-tramo pytest tests/test_tramo_extension.py
```

Note: a few tests near the bottom (retired `/api/v1/workflows` routes, ported
event emitters, `docker_service` not double-emitting `app.stopped`) assert
plan-45 behaviour of the **panel core**, not of this extension — they are kept
here for historical coverage and only pass against a panel checkout that
includes those changes.
