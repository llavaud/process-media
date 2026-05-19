# Contributing to process-media

Thanks for your interest! `process-media` is a small, personal-scale
open-source project; contributions of any size are welcome — bug
reports, feature requests, documentation tweaks, or pull requests.

## Reporting a bug

Open an issue with the **Bug report** template. The more of the
following you can include, the faster it will be triaged:

- `process-media --version` (or commit SHA if running from source)
- Distribution + Python version (`python3 --version`)
- The exact command you ran
- The full output (use `-v` for verbose logs)
- A minimal `process-media.yaml` that reproduces the issue
- One or two sample files if the problem is media-specific (please
  scrub anything sensitive from EXIF first)

## Proposing a feature

Open an issue with the **Feature request** template before sending a
large PR. Brief discussion up front avoids wasted work on both sides.

## Sending a pull request

1. **Fork** the repository and create a branch from `master`. Use
   conventional names: `feat/PROJ-123-short-description`,
   `fix/short-description`, `docs/…`, `test/…`, `refactor/…`.

2. **Set up your environment**:
   ```bash
   make install      # creates .venv, installs editable + dev extras
   ```

3. **Run the test suite + linter** before pushing:
   ```bash
   make check        # ruff check + pytest
   ```

4. **Follow the existing style**:
   - Python: ruff is configured in `pyproject.toml`; `make format`
     applies it.
   - Types: keep the codebase fully annotated (mypy strict is
     configured but not enforced in CI today).
   - Tests: add a unit test for any bug fix or new behaviour.
     `pytest -q` should always pass.

5. **Commit messages** follow [Conventional Commits][cc]:
   `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, etc.
   Breaking changes use `!` and a `BREAKING CHANGE:` footer.

6. **Open the PR** against `master`. Describe what changed and why,
   reference any related issue (`Closes #N`), and confirm the test
   plan.

## Releasing (maintainers only)

See the "Releasing a new version" section of the
[README](README.md#packaging-debian--ubuntu) for the full flow:
bump version → `make check` → `make deb && make deb-lint` →
`make apt-publish && make apt-push` → tag + release on GitHub.

## License

By contributing, you agree that your contributions will be licensed
under the [MIT License](LICENSE).

[cc]: https://www.conventionalcommits.org/
