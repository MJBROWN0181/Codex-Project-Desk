# Trunk/work and Project Desk records

Feature records and source worktrees serve different purposes. Project Desk
keeps reports, ideas and dated chat logs in the project's records layout. Code
continues to use the repository's existing Git worktrees and branch policy.
No worktree is created, moved, reset, synchronized, or deleted by this adapter.

Example of a trunk/work layout:

```text
ExampleApp/
  Trunk/                         main; existing release gates
  Field Tech/                    work/field-tech; actual source checkout
  Features/Field Tech/Chat/       dated records and pass-on logs
  Features/Field Tech/Audit/      dated report copies
```

Existing projects opt into records individually. Enabling records adds
directories; it does not replace the existing worktree layout or migrate code.

## Feature routing

In **Project folders**, add/select the feature. **Find existing worktrees**
lists the configured repository's registered checkouts. **Bind selected feature
to checkout** saves the path and expected branch. Trunk, detached checkouts,
and unrelated repositories cannot be bound. A unique existing `work/<slug>`
branch can be resolved without an explicit binding; no branch is invented or
created from the name.

Each managed task starts a fresh dated chat in that verified source checkout.
The message supplies the separate feature records folder, current branch,
HEAD, dirty state, and latest matching completed handoff. The agent is instructed
to read source `AGENTS.md` and the existing shared handoff/nightly review before
edits. Files outside the current task, including other dirty work, are preserved.

Branch and HEAD are rechecked immediately before native chat creation and before
queueing the message. A changed checkout stops delivery for a fresh review;
there is no retry into another checkout. This is a point-in-time guard, not a
filesystem lock preventing an external actor from changing branches afterward.
The agent must still recheck Git state before editing.

Queued additions and wrap-up stay in the current chat. They may refresh HEAD
after an authorized commit on the same branch; branch changes stop continuation.
After a confirmed successful wrap, the record includes checkout, branch, HEAD,
dirty files and the final handoff. The agent also maintains the repository's
existing shared handoff convention; Project Desk's dated copy supplements it.
A handoff from another checkout/branch cannot silently become the new feature's
continuation. Legacy Git handoffs without checkout identity require verification
and a new wrap-up. Finished chats stay available.

## Audits and promotion

Multiple registered worktrees, explicit `trunkWorkflow` metadata, or a detected
`docs/TRUNK-WORKFLOW.md` / `.config/trunk.json` enables the guarded workflow.
For unusual conventions, set up a verified feature binding; names alone cannot
prove that a branch is intended for feature work.

Broad audits including trunk or multiple checkouts are read-only: the engine
does not run its repair pass. Feature fixes must use an audit of the selected
feature checkout only. Cross-checkout audit-fix sends are rejected rather than
silently narrowing the original audit's scope. Advisor reports remain advisory.

The generic **Push to GitHub + release** operation is blocked for trunk/work
repositories before committing, tagging, pushing, or publishing. Use the
repository's documented compatibility checks, exact-commit gate, approval,
promotion, synchronization and deployment process. Neither an audit grade nor
a successful wrap-up authorizes a release.

## Verification

`python -m unittest test_worktree_workflow test_project_folders -q` exercises real
disposable Git worktrees without remotes, with synthetic chat completions. It
covers source routing, dirty-file preservation, binding checks, stale branch/HEAD
rejection, handoff Git evidence, read-only broad audits, and early release blocks.
`python check_project_folders.py` verifies the UI with an isolated database and
stubbed Codex transport. These checks do not establish live desktop delivery or
production readiness. No existing project is migrated by the tests.
