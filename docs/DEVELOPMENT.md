# Development

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/makereel web          # the server serves src/makereel/web directly; reload the page after edits
```

The web UI has no build step. It is plain ES modules served from `src/makereel/web/`.

## Checks

```bash
.venv/bin/python -m pytest      # unit tests: no network, no ffmpeg, no models
.venv/bin/ruff check src tests  # lint (rules in pyproject.toml)
```

Tests run against a temporary output folder and config (`tests/conftest.py`), so your real reels are never touched.

## Conventions

- **Layers:** `core` → `services` → `api` / `cli`. `core` never imports `services`, `api` or `web`.
  The web UI only talks to `/api/v1`.
- **Names:** Python uses `snake_case` for modules and functions and `PascalCase` for classes.
  JavaScript uses `camelCase`. Files and folders are lowercase. Reels are `reel_NN`.
- **Errors:** raise a `MakereelError` subclass with a message a user can act on, plus a `hint` when
  there's an obvious fix. Never `print` an error and carry on silently.
- **Logging:** `log = logging.getLogger(__name__)`. Use `logs.spawn()` for helper threads so their logs
  reach the right job.
- **External tools:** always go through `media.binary()` / `media.run()`, never a bare `"ffmpeg"`.
- **Paths from requests:** always go through `library` helpers, which refuse anything outside the library.
- **Config:** a new deployment option goes in `config.Env` + `.env.example` + CONFIGURATION.md.
  A new user setting goes in `SETTINGS_DEFAULTS` with validation in `save_settings`.
- **Commits:** short imperative subject ("Add folder delete endpoint"), body explaining why.

## Adding an API route

1. Put the logic in a service (`services/…`) so the CLI can use it too.
2. Add the route in `api/routes.py`:
   ```python
   @api.post("/folders/{folder}/archive")
   def archive(req: Request):
       return library.archive(req.params["folder"])
   ```
3. Add the client call in `web/js/api.js`, then use it from a view.
4. Document it in `docs/API.md` and add a test.

## Where things are

See [ARCHITECTURE.md](ARCHITECTURE.md) for the module map, data flow and state model.
