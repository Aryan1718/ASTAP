# Contributing to ASTAP

Thanks for contributing.

## 1. Before You Start
- Read the architecture and stage contracts in `README.md` and project docs.
- Check open issues before starting work.
- For larger changes, open an issue first to align design.

## 2. Development Setup
1. Fork and clone the repository.
2. Copy environment variables:
   - `cp .env.example .env`
3. Apply database schema:
   - `./scripts/apply_supabase_schema.sh`
4. Start local stack:
   - `docker compose up --build`

## 3. Branch and Commit Style
- Branch naming examples:
  - `feat/discover-endpoint-detection`
  - `fix/ingest-snapshot-hash`
- Keep commits focused and descriptive.
- Prefer conventional prefixes (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`).

## 4. Code Standards
- Preserve stage boundaries: each stage reads durable inputs and writes durable outputs.
- Maintain idempotency and retry safety for worker jobs.
- Avoid breaking API contracts or schema assumptions.
- Add or update tests when behavior changes.

## 5. Pull Request Checklist
- [ ] Change is scoped and documented.
- [ ] Tests added/updated where needed.
- [ ] Existing tests pass locally.
- [ ] No secrets in code, logs, or artifacts.
- [ ] Migration changes are safe and reversible where possible.
- [ ] PR description explains the why, what, and risk.

## 6. Reporting Bugs
Please include:
- Environment details
- Steps to reproduce
- Expected behavior
- Actual behavior
- Relevant logs or screenshots

## 7. License
By contributing, you agree that your contributions are licensed under the MIT License in [LICENSE](LICENSE).
