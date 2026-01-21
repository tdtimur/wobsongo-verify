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

## Set Up Environment

We use `uv` for dependency management. Install the dependencies with:

```bash
uv install
```

## 3. Run Tests

Ensure everything is working correctly before you start:

```bash
pytest tests/
```

# Data Privacy & Safety Policy

**CRITICAL**: Do not commit any real user data, private health records, or proprietary knowledge base dumps to this repository.

- **Use Dummy Data**: When writing tests or examples, use the dummy data provided in tests/data/.
- **No API Keys**: Never hardcode OpenAI or Vector DB keys. Use environment variables (e.g., .env).

# Pull Request Process

- Create a new branch for your feature: git checkout -b feature/my-new-feature
- Commit your changes using clear messages: git commit -m "Add Qdrant support to Retriever"
- Push to your branch: git push origin feature/my-new-feature
- Open a Pull Request against the main branch.
- Wait for a maintainer to review. We aim to review all PRs within 72 hours.

# Reporting Bugs

If you find a bug, please open an issue on GitHub. Include:

- A clear title and description.
- Steps to reproduce the bug. A clone or a fork of the repo with reproduction steps is ideal.
- The version of Python and dependencies you are using (although we always recommend using the versions in uv.lock).

# Security Vulnerabilities

If you discover a security vulnerability, please do NOT open a public issue. Email [tahta@impactscope.com](mailto:tahta@impactscope.com) instead. We will work with you to patch it before disclosing it publicly.

By contributing to this project, you agree to abide by our Code of Conduct.
