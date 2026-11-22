# Small-change commit workflow

Requested by the repository owner on 22 November 2026.

During active coding sessions, invoke the independent commit guard after each
small coherent completed code change. Batch edits that must work together;
do not commit every keystroke or knowingly broken intermediate states.

1. Identify task-owned paths and preserve unrelated user edits.
2. Run suitable checks and the required independent review. Fix confirmed issues.
3. Ask the commit guard to inspect the proposed paths and staged diff using
   the role brief in .agents/commit-guard.md.
4. Stage explicit paths. Exclude secrets, real .env files, credentials, tokens,
   private databases, account history, licensed content and generated caches.
   Inspect new files and ignore rules before staging.
5. Commit locally with a concise descriptive message. Inspect the resulting
   commit and report its identifier and remaining changes.
6. If checks are blocked, defer normal automatic commits. An explicit request
   to save the current work may use a clearly described checkpoint commit with
   pending checks in its body. A checkpoint is not deployment acceptance.

Do not push without authorization for the intended remote. Never force push,
reset, amend, discard changes, bypass failing hooks or alter trading permissions
to make this workflow succeed.

The commit guard is invoked during active coding work. It is not a permanently
running service and does not monitor edits outside an active Codex session.
