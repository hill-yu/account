# 2026-09-24 production runtime source archive

This directory preserves the source and build artifacts copied read-only from
`/srv/adx-account-isolated-collector` on the production host before retiring
the old mid-platform. It is an archive, not a deployment candidate.

- Server Git clone: `/srv/gitcode/adx-account-isolated-collector`, clean `master`
  at `86d67e8b1e2bdaa57967c80042b605a44c9cccc4` when inspected.
- Runtime directory: `/srv/adx-account-isolated-collector`, which has no `.git`.
- Source extraction: remote `tar` stream, SHA-256 of local transport archive
  `766C0054130A2731F922DEB5658622B5CB40C67B07D3E2BB593CF078A7749C15`.
- Excluded from the transport archive: `.env`, SQLite database and WAL/SHM,
  backup directories, virtual environments, `node_modules`, Git internals,
  Python bytecode, and caches. None of those belong in Git.
- The transport archive is a temporary local artifact and is not committed.
- Historical operator documentation and notes from the runtime directory are
  not duplicated here; they remain in the already committed server clone at
  the commit above. This archive captures the executable source, tests,
  migration files, deployment templates, and the actual served frontend build.

The committed files below `backend`, `collector`, `frontend`, `deploy`, and
`scripts` are the captured production runtime tree. Historical repository
code and documentation remain available at the server clone commit above.
