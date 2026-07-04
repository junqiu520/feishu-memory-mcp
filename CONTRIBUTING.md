# Contributing

Thanks for taking an interest in `feishu-memory-mcp`. This document covers
how we work — please read it before opening a PR.

By participating, you agree to abide by the [Contributor Covenant Code of
Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
Be patient with newcomers; be direct about technical disagreements.

## How to start

```bash
# 1. Clone
git clone https://github.com/your-org/feishu-memory-mcp
cd feishu-memory-mcp

# 2. Install with the dev extras (test + lint + mypy)
pip install -e ".[dev]"

# 3. Run the test suite
pytest                         # full suite
pytest tests/test_setup.py     # one file at a time

# 4. Lint & type-check
ruff check src/ tests/
mypy src/
```

The project requires **Python 3.11+**. Node.js (>= 18) is only needed at
runtime through `lark-cli`; tests do not require it.

## Tests

We follow strict TDD for any feature or bug fix:

1. **Write a failing test** that captures the desired behavior. It should
   fail before your implementation.
2. **Implement** the smallest change that makes the test pass.
3. **Refactor** while keeping the test green.
4. **Commit** with a Conventional Commits message.

Tests live next to the code they exercise in `tests/`. Use
`pytest-asyncio` (already configured via `asyncio_mode = "auto"` in
`pyproject.toml`) for async tests. For tests that need Feishu, prefer
injecting a fake client over mocking subprocesses.

Run the full suite before pushing. There must be **zero skipped tests**
in your diff unless the skip is documented in the test body with a
reason.

## Style

Configured in `pyproject.toml`:

- **Ruff** for lint + format (`ruff check src/ tests/` and
  `ruff format`). Line length is 100.
- **mypy** for type checks; the project is fully type-annotated.
- **No emojis** in code or docs (we keep tone neutral for downstream
  tools).

A `pre-commit` hook that runs `ruff check --fix` and `mypy` is
recommended but not yet enforced in CI — please run them locally before
pushing.

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix      | When                                                |
|-------------|-----------------------------------------------------|
| `feat:`     | New user-facing feature                             |
| `fix:`      | Bug fix                                             |
| `chore:`    | Maintenance, deps, internal refactor                |
| `docs:`     | Documentation only                                  |
| `test:`     | Adding or fixing tests                              |
| `refactor:` | Code change that doesn't change behavior            |
| `perf:`     | Performance improvement                             |

Examples:

```
feat(services): add memory_count tool to FastMCP server
fix(feishu): handle empty stderr from lark-cli gracefully
docs(tool-reference): document filter shape for memory_query
```

## PR process

1. **Branch from `main`.** Name your branch `feat/<short>` or
   `fix/<short>`.
2. **Write tests first.** The PR description should briefly explain how
   TDD was applied.
3. **Run the full suite** locally and confirm all tests pass:
   ```bash
   python -m pytest tests/
   ruff check src/ tests/
   mypy src/
   ```
4. **Reference the spec section.** This project is spec-driven; your PR
   description should mention which section of
   `docs/superpowers/specs/2026-07-02-feishu-memory-mcp-design.md`
   the change implements or modifies.
5. **Keep the diff small.** Each PR should do one thing. Split larger
   work into stacked PRs.
6. **One approval** from a maintainer is required to merge. Squash-merge
   is the default.

If your PR touches `src/mcp_memory/feishu/runner.py` or
`src/mcp_memory/config.py`, please double-check that **no secrets** are
introduced — `feishu_app_secret` must remain `SecretStr` and must not
be logged.

## What NOT to do

- **Do not add new third-party dependencies without discussion.** Open an
  issue first; the PR should justify the dep in terms of size, license,
  and maintenance burden. We are deliberately lean (`pyproject.toml`
  lists 7 runtime deps; we want to stay there).
- **Do not bypass the secret-safe pattern.** `SecretStr` end-to-end is a
  hard requirement. Never log, print, or serialize
  `feishu_app_secret.get_secret_value()`.
- **Do not skip tests for "MVP speed".** Every test must pass before
  merge. Use `pytest.mark.xfail` only with a linked issue and a comment.
- **Do not commit `data_dir/`, `.feishu_memory/`, or `__pycache__/`.**
  These are git-ignored, but check `git status` before pushing.
- **Do not enable network calls in unit tests.** Services should accept
  client interfaces; tests inject fakes. Integration tests that hit real
  Feishu go in a separate suite (gated behind an env flag, not in
  default `pytest`).
- **Do not add CLI commands that duplicate MCP tools.** The CLI is
  ops-only. New `cli` subcommands must not be `add` / `query` / `get` /
  `update` / `delete` / `list` / `count`.

## Release process

Maintainers only:

1. Update `CHANGELOG.md` with the next version section.
2. Bump `version` in `pyproject.toml`.
3. Tag `vX.Y.Z` and push.
4. The CI publish job uploads to PyPI.

Bug fixes go to `0.1.x`. Breaking changes bump the minor (`0.2.0`)
until we hit `1.0.0`.

## Communication

- File issues for bugs and feature requests.
- Use draft PRs for work-in-progress; convert to ready-for-review when
  tests pass and CI is green.
- Maintain a friendly, technical tone in review comments.

Happy hacking.
