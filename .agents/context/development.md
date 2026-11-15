# Stripe development and verification

## Environment

Use Python 3.12 and a working core Eventyay environment with PostgreSQL and Redis.
Core's README and `app/pyproject.toml` specify native libraries and other runtime
requirements. This plugin does not have its own `manage.py` or server.

The following example assumes existing checkouts and paths you supply. Run the
first commands from any directory, replacing the two example absolute paths:

```sh
export EVENTYAY_CORE=/absolute/path/to/eventyay
export EVENTYAY_PLUGIN=/absolute/path/to/eventyay-stripe
cd "$EVENTYAY_CORE/app"
uv sync --all-extras --all-groups
. .venv/bin/activate
uv pip install --python "$EVENTYAY_CORE/app/.venv/bin/python" -e "$EVENTYAY_PLUGIN"
python manage.py migrate
cd "$EVENTYAY_PLUGIN"
make
```

Configure the local core environment before migrations. `make` compiles
translations and requires gettext. Start `python manage.py runserver` from core's
`app/`, and restart workers after plugin installation. Core's development Docker
stack can install editable plugins mounted from `plugins/`; see core's
`app/entrypoint.sh` and `docker-compose.yml` for mode/stamp behavior.

Verify that Python imports your checkout after every dependency sync:

```sh
python -c 'import eventyay_stripe; print(eventyay_stripe.__file__)'
```

## Tests

`.github/workflows/tests.yml` clones core `dev`, synchronizes its environment,
installs this plugin in editable mode, and runs tests from this repository. It
provides PostgreSQL 15 and Redis 7. With those disposable local services available
and the environment above activated, reproduce its settings:

```sh
cd "$EVENTYAY_PLUGIN"
EVY_RUNNING_ENVIRONMENT=testing \
EVY_POSTGRES_HOST=localhost EVY_POSTGRES_PORT=5432 \
EVY_POSTGRES_USER=postgres EVY_POSTGRES_PASSWORD=postgres \
EVY_POSTGRES_DB=eventyay-db \
DJANGO_SETTINGS_MODULE=eventyay.config.settings \
PYTHONPATH="$EVENTYAY_CORE/app" pytest -p no:env tests
```

The command disables the `pytest-env` plugin with `-p no:env` so the explicit
environment is used. Without that flag, the plain `[tool.pytest_env]` entries in
`pyproject.toml` overwrite the supplied database variables. CI uses those defaults.
The values above are local CI-style test credentials only. Adjust them for your
disposable test database; never point this command at production. For focused
runs replace `tests` with the relevant test module from [the flow map](flows.md).

`pyproject.toml` requires Python `>=3.12,<3.13`; the README's Python 3.9+ statement
is stale. It declares a `test` extra and a `dev` dependency group, not a `dev`
extra. Install test extras with `uv pip install --python "$EVENTYAY_CORE/app/.venv/bin/python" -e '.[test]'`
from this repository; use the declared Ruff version for development tools.
Style checks are `ruff check .` and `ruff format --check .`; see
`.github/workflows/ruff.yml`. The default CI selection covers helper/validation/privacy tests. Also run
`pytest -p no:env tests eventyay_stripe/tests -rs` for the nested provider/checkout/webhook suite
with the same explicit Django settings and database environment. The webhook
module and checkout test remain unconditionally skipped because their
multidomain/session setup is incomplete; this command reports those skips rather
than proving those flows work. See [test gaps](flows.md#test-map-and-gaps).

## Documentation and PR checks

For changes limited to agent Markdown, inspect referenced source paths, validate
skill frontmatter, run `git diff --check`, and check packaging when adding tracked
files. Agent context is not part of a Sphinx documentation tree here. Report
source checks separately from application tests; no live payment test is implied.

Branch from upstream `dev`, push to the appropriate contributor remote, and open
a PR against `dev`. Inspect remotes rather than assuming `origin` is a fork.
Record core/plugin revisions for integration tests. For changed contracts,
coordinate a core PR and deployment ordering; docs-only PRs need no lock update.
