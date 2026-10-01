# Environment (public)

This file describes the computation environment WITHOUT credentials.

- Analysis language: Python 3 (deterministic scripts; dependencies pinned in
  requirements files at export time) or Node.js 20+ for pipeline replay.
- External data APIs used by the benchmark (read-only, public):
  - OpenAlex https://api.openalex.org (mailto contact header)
  - NCBI E-utilities https://eutils.ncbi.nlm.nih.gov (API key optional; the
    author's key is NOT stored here)
  - Crossref https://api.crossref.org (mailto contact header)
- No production credentials, private keys, or connection strings exist in this
  repository; run-time secrets are read only by the author from his own secure
  store.
- Randomness: no seeded random processes planned for primary analysis;
  benchmark repetitions (3 per task) are API-level repetitions documented in
  run logs.
- Offline verification entry point: `bash code/verify_public_export.sh`
  (checks every committed file against the allowlist and scans for
  secret/identifier patterns). All later analysis scripts will include a
  `make check` target that reproduces figures/tables from data/processed.
