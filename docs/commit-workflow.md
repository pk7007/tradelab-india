# Small-change commit and push workflow

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
5. Commit with a descriptive message. Inspect the commit identifier,
   changed paths and remaining changes.
6. Push automatically to the approved repository:
   https://github.com/pk7007/tradelab-india.git (remote origin).
   Verify fetch and push destinations before every push; never expose embedded
   credentials. Use the current branch's upstream only when it points to this
   origin. For a new branch, publish the same-named branch to this approved
   origin and set its upstream. Never redirect a feature branch to master or
   push unrelated branches or tags.
7. Use an ordinary fast-forward push. If authentication fails, the destination
   changes, the upstream is unexpected or the remote has diverged, preserve
   the local commit and report the blocker. Never force push, rewrite history,
   merge remote changes automatically or bypass hooks to make a push succeed.
8. Verify the remote branch tip equals the intended local commit and report
   the commit link and any remaining uncommitted work.
9. If checks are blocked, defer ordinary automatic commits and pushes. An
   explicit request to save or publish current work may use a clearly described
   checkpoint with pending checks in its body. A checkpoint is not deployment
   acceptance.

This is standing authorization for this reviewed commit-and-push workflow;
do not ask again for routine safe pushes. It does not authorize changes to
broker permissions, funds, limits, strategy promotion or deployment.

The commit guard is invoked during active coding work. It is not a permanently
running service and does not monitor edits outside an active Codex session.
