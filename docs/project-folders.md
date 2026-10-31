# Project folders and chat continuity

New projects created with **Add project** create a named records directory under
`Desktop/Projects`. A source folder entered in the editor remains the code
location; files are never reorganized. A name collision stops creation instead
of adopting or overwriting an existing directory. Imported/API cards retain their
existing behavior unless explicitly opted in with `createFolders: true`.

Each card's **Project folders** button manages this workflow. Existing projects
must use **Enable project folders** individually. Enabling may add records directories to the existing named project folder,
but never overwrites code or adopts a records folder owned by another card.
Enabling does not move existing code or historical chats.

```text
Project Name/
  Features/Feature Name/
    Audit/
    Advisor/
    Chat/
    New Ideas/
  Project Audit/
  Project Advisors/
  Marketing/Images/
  Marketing/Social Media Ads/
  Brain Dump/
  Branding/
  Chat/
```

Select **Whole project** or a feature, describe the task, and click **Start new
chat**. The chat starts in the verified application source checkout, with its
records folder and latest completed handoff supplied in its message. Titles use the desktop's
local date and time followed by `Chat`; record directories add a request suffix
to avoid same-second collisions. Ordinary reviewed sends, accepted suggestions,
and audit-fix sends also create fresh dated chats for opted-in projects.
Queued additions and Wrap up stay in the current chat.

**Wrap up work** requests a final handoff. After confirmed successful completion,
Project Desk stores observed turn items in `Chat/<dated chat>/session.json` and
the final handoff in `Pass On Log.md`. Failed or interrupted wrap turns do not
become the next handoff. Completed chats remain in Codex and cannot be reused by
the managed workflow. Resume a paused project before starting new work. The new
chat reads the most recently completed handoff from its selected folder, not
from a different feature. Checkout, branch, HEAD, and dirty state are recorded
on wrap-up and checked before new work. Established repository handoffs remain
authoritative and are updated by the agent as required by the project rules.

Audit and advisor reports are copied as dated JSON and Markdown records when
saved. Grades appear in filenames when the report provides one. Whole-project
reports go in Project Audit / Project Advisors; reports launched with a feature
selected go in that feature's Audit / Advisor directory. A feature selects the
records context, not an automatic code-isolation boundary: the report's actual
audited source folders and findings remain the authority for inspection scope.
Earlier report files are retained. **Save idea** writes to the selected feature's
New Ideas or the whole project's Brain Dump.

These are private local records, including chat contents. Existing repository
ignore rules still apply; review Git staging before publishing. No old chats are
automatically exported or migrated. This module records turns monitored by
Project Desk, not unrelated messages typed directly into Codex. No promise of
automatic export can be made when Project Desk is offline.

Developer checks: `python -m unittest test_project_folders -q` uses temporary
folders and mocks native sending. Browser checks should likewise use an isolated
database and stub the native worker. They do not prove desktop chat delivery.


For trunk/work repositories, see [worktree compatibility](TRUNK-RECORDS.md).
Choose a feature and use **Find existing worktrees** and **Bind selected feature
to checkout** when its branch cannot be resolved uniquely. Feature work cannot
fall back to trunk. Broad trunk/work audits run read-only; automatic fixes must
target only the selected feature checkout. The generic release button is blocked;
use the repository's approved promotion process.
