# Contributing to Wobsongo Verify

Thank you for your interest in contributing to Wobsongo Verify! We are an open-source project dedicated to building standard infrastructure for automated claim verification.

Whether you are fixing a bug, adding a new Vector DB connector, or improving our documentation, we welcome your help.

## Quick Start

### 1. Fork and Clone

Fork this repository to your own GitHub account and clone it locally:

```bash
git clone [https://github.com/kairosedubf/wobsongo-verify.git](https://github.com/kairosedubf/wobsongo-verify.git)
cd wobsongo-verify
```

## 2. Set Up Environment

We use `uv` for dependency management. Install the dependencies with:

```bash
uv install
```

## 3. Quality Assurance

All PRs must include tests and maintain **at least 80% line coverage**.

```bash
# Run the full suite
pytest tests/

# Run with coverage report
pytest --cov=wobsongo_verify --cov-report=term-missing tests/
```

**Test conventions:**

- File names: `test_<module>.py` — one file per source module
- Fixtures: define shared fixtures in `tests/conftest.py`
- Test data: use `tests/data/` only — never real datasets

**Unit vs. integration tests:** Mark tests that call live external services with `@pytest.mark.integration` so they can be skipped in fast local runs:

```python
@pytest.mark.integration
def test_retriever_queries_qdrant():
    ...
```

```bash
pytest tests/ -m "not integration"   # unit tests only (default in CI)
```

**Linting:** Run before opening a PR — CI will reject on failures:

```bash
ruff check . && ruff format .
```

# Data Privacy & Safety Policy

**CRITICAL**: Do not commit any real user data, private health records, or proprietary knowledge base dumps to this repository.

- **Use Dummy Data**: When writing tests or examples, use the dummy data provided in tests/data/.
- **No API Keys**: Never hardcode OpenAI or Vector DB keys. Use environment variables (e.g., .env).

# Pull Request Process

- Clone/fork the repo.
- Create a new branch for your feature: `git checkout -b feature/my-new-feature`
- Commit your changes using clear messages: `git commit -m "feat(vector): add Qdrant support to Retriever"`
- Push to your branch: `git push origin feature/my-new-feature`
- Open a Pull Request against the main branch.
- Wait for a maintainer to review. We aim to review all PRs within 72 hours.
- Make sure that all checks pass (tests, linting, coverage) in GitHub Actions.
- Once you get an approval, one of the project maintainers will merge your PR.

# Reporting Bugs

If you find a bug, please open an issue on GitHub. Include:

- A clear title and description.
- Steps to reproduce the bug. A clone or a fork of the repo with reproduction steps is ideal.
- The version of Python and dependencies you are using (although we always recommend using the versions in uv.lock).

# Security Vulnerabilities

If you discover a security vulnerability, please do NOT open a public issue. Email [tahta@impactscope.com](mailto:tahta@impactscope.com) instead. We will work with you to patch it before disclosing it publicly.

By contributing to this project, you agree to abide by our Code of Conduct.
