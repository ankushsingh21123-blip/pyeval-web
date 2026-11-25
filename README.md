# pyeval-web
Small full-stack app: static frontend, Python serverless API, Postgres.

- Stores fixed tasks and pre-written candidate answers; "Run tests" scores a stored answer against test cases (via the pyeval harness) and saves the run.
- `POST /api/lint` parses pasted code with `ast` only. Client code is never executed; runs accept only an `answer_id` of a stored fixture.
- Tests run in GitHub Actions against a real Postgres service container.
- Env: `DATABASE_URL` (set in hosting, never committed).

Built with AI assistance (Instinct) for Ankush Singh.
