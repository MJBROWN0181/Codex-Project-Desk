# Codex Project Desk

Project Desk version 2.1.1 helps you track software, website, app, business, and document-rendering projects in one local dashboard. See the next action and last-worked time for each project, review recommendations, and follow work sent to Codex. It also provides saved drafts, project archives, readiness audits, and dark/light themes.

This is a local desktop tool, not a hosted or cloud-sync service. Manual tracking needs only Python. Automated work requires compatible local Codex tooling; audit grades describe the checks performed and do not guarantee production readiness.

## Run locally

Download or clone this repository into a folder of your choice. It contains the
Project Desk application and synthetic test fixtures, with no saved projects,
chat exports, account credentials, or browser profiles.

1. Install Python 3.10 or newer.
2. Open a terminal in the downloaded folder and run `python server.py`.
3. Open [Project Desk](http://127.0.0.1:8789). The first-run wizard checks optional tools and
   explains how to add your first project. Choose **Start with an empty desk**
   or **Add my first project**. No sample projects or local indexes are imported.
4. On Windows, `Open-ProjectDesk.ps1` opens a standalone window. Optionally run
   `Install-DesktopShortcuts.ps1` to create the desktop icon and a combined Codex
   launcher. The combined launcher replaces an existing `Codex (OpenAI).lnk`
   shortcut only if one is present. Shortcut changes happen only when you run
   that installer.

The wizard is available again through **Getting started** in the header. Python
is the only requirement for manual tracking. Codex features additionally need
an installed, signed-in Codex CLI; GitHub features need Git and a signed-in
GitHub CLI (`gh`). The wizard checks tool availability, not account sign-in.

Add projects manually with **Add project**. **Refresh Codex index** explicitly
imports this computer's saved metadata, if available; ordinary startup never
imports it. Personal runtime state stays in the Git-ignored `data/` folder.
Do not upload that folder when sharing the app. `PROJECT_TRACKER_DATA` can point
to another local data directory; exports are read from that directory too.

From the repository folder, the basic launch command is:

```powershell
python server.py
```

For the separate Windows app window, use:

```powershell
.\Open-ProjectDesk.ps1
```

The standalone window needs Microsoft Edge or Google Chrome. Codex automation,
chat opening, and desktop shortcuts currently target Windows; manual tracking
can also be used through the local browser page. Codex integration depends on
the installed CLI exposing the app-server and queue commands used by this app.
Signing into a CLI alone does not verify that every integration is supported.

## First project workflow

1. Click **Add project**, enter its name and type, and save. Add an existing local
   project folder for audits and an `owner/repository` value for GitHub features.
2. For a linked local Codex chat, click the next action, search for the destination
   chat, and review or edit the recommended step, reason, and instructions.
3. Click **Send to Codex**. The card tracks the delivered work until the exact
   Codex turn finishes. Add content while it works to queue follow-up instructions.
4. Use **Mark done manually** for work you finish yourself. Codex work updates
   automatically when its tracked turn completes.

A new empty desk has no linked chat. Link one by choosing an existing local chat
in the next-action review, explicitly importing a saved Codex index, or using the
optional installed `spd` skill described below. Audits differ from next-action
sends: after review, they create a new chat named **Audit** in the project folder.

## Work, queue, and finishing controls

Audit reports highlight the grade, highest-priority findings, failed checks,
and verification gaps. Other findings, check results, and full reviewer evidence
remain expandable. Copy fix prompt and Send to Codex are available beside the
recommended prompt. Sending first opens an editable review. The final Send to Codex
click creates a new local chat named Audit in the project's existing folder and
delivers the reviewed fixes there, never to an older chat. Cancelling creates no
chat. The project must have an existing local folder. Normal next-action reviews
use a searchable chat picker with readable, wrapping rows in dark and light mode.
Audit review never generates a replacement recommendation. Audit edits save in
a separate browser draft, keeping the existing next-action draft intact. Advisor fix prompts have the same workflow;
unanimous shelving reports expose no fix-prompt copy or send controls.

Repair prompts reference the full saved report, ask Codex to select relevant
available tools and installed skills, verify findings, prioritize risk, apply
focused fixes, rerun checks, and report remaining gaps. Large recommendations are
read from the complete saved report instead of silently truncating them. Paused or
working projects retain their existing queue controls. Release and deployment
actions remain separate from audit remediation.

Panel of advisors runs three independent read-only reviews: a code advisor grades
implementation and feasibility; a social director grades whether a defined group
would use and return to the project; a marketing advisor grades positioning,
differentiation, reach, and cost/value. Grades apply separately to each remit.
Advisors use live web research where useful, cite sources, distinguish evidence
from assumptions, and consider unconventional/niche/internal-use ideas fairly.
They are instructed to be candid and specific, without flattery or filler.

Each advisor first gives a grade and a continue/pivot/shelve/insufficient-evidence
verdict. Only after those independent verdicts are collected can supported fix
prompts be generated. If all three give grounded shelving verdicts, that second
phase is skipped entirely: the report contains reasons to shelve and no fix
prompts. Missing/failed/unsupported reviews cannot count as negative votes.
The report is saved separately from the Finish agent team audit, includes
copyable prompts when appropriate, and never applies fixes or archives the
project automatically. It is a bounded evidence-based assessment, not proof of
future adoption or revenue. Report files are saved in the local data/reports folder.

Unreviewed means an imported project has not yet been reviewed in Project Desk. Accepting or dismissing its suggestion, saving project details or an edited review draft, generating a successful agent recommendation, sending/queuing work, or starting a project audit clears it to Active. Mark reviewed also clears it directly without changing Last worked on. Imports, connection checks, and pinning alone do not count as reviews. Explicit Waiting, Paused, and Complete statuses are preserved. A one-time migration repairs old stuck Unreviewed labels using saved review/work evidence; untouched imports stay Unreviewed.

Sending a reviewed next action immediately reserves the project as working. A delivery receipt means the message arrived; completion waits for the exact Codex turn to report completed. While working, project edits and new suggestions are held. Add content saves durable FIFO additions, automatically delivered to the same local chat after completion. The saved final answer updates the card and activity. When the queue is empty, an agent recommends a new step for review; suggestions are never executed automatically. A finished turn does not mean the whole project is complete.

Pause lets the current turn finish and holds queued additions. Resume drains them. Wrap up work schedules a handoff in the same chat after the current turn, then pauses additions. A failed or interrupted turn holds the queue and shows Needs attention. Check work status acknowledges a known failed turn or failed delivery and leaves additions paused for review; ambiguous deliveries are checked without automatic retransmission. Queue receipts and state survive restarts. Interrupted audits/releases are never replayed automatically. Completion checks run about every five seconds; active-chat discovery about every thirty seconds. Local saved Codex history must expose the turn and final status. Cloud chats remain link-only.

Push to GitHub + release commits the project repository's nonignored changes, pushes its current named branch, creates the next annotated patch-version tag, publishes a GitHub release, and verifies publication. This button publishes; it does not create a draft. It validates the configured repository and all push destinations, checks obvious credential files and private keys, rejects behind/diverged branches, and preserves partial progress on failure. No force push, reset, stash, or cleanup is used. A clean unchanged retry resumes its saved incomplete release after checking tag identity. Git and signed-in GitHub CLI access are required. Set the actual local project folder and owner/repository in Edit project first.

Am I done? inspects the actual folder, applies focused required fixes, and reviews again. Finish agent team adds a boss coordinating six specialist reviews: security, errors, writing/AI slop, desktop/mobile UI when applicable, weak spots, and improvements. Specialists inspect independently with at most three running at once; only the boss's repair pass writes files. Existing edits get a local recovery baseline before repairs. Missing access, failed checks, and untested device/authenticated flows stay visible. Agents do not publish, deploy, commit, or send messages as part of reviews. Reports and copyable follow-up prompts are saved locally in data/reports; recovery baselines stay in data/audit-baselines. Review work can take several minutes and progress is shown on the card.

Grades: A ready to use; B almost done and usable; C minor fixes or required features remain; D work in progress and not ready for real use; F not working. A requires supporting checks and no material gaps. Optional improvements alone do not prevent an A. Automated review is bounded to one repair/recheck cycle; unresolved findings stay in the report.

Website projects can have a configured HTTP(S) URL. If it is empty, Check site detects declared website metadata from the project, including CNAME, a homepage canonical/og:url tag, package homepage, a labelled README website link, or saved GitHub homepage metadata. It saves an unambiguous detected address into Website URL; an explicit address always wins. Unrelated documentation and repository links are not treated as the website. Up/Down shows the checked address, timestamp, and response code; checks run roughly once per minute and through Check site. This is a point-in-time check from this computer, not a global uptime guarantee.

## Drafts, focus, and latest replies

An optional installed `spd` (Send to Project Desk) skill registers the current
project and verified local Codex chat automatically. Type `spd` or `$spd` in that
chat, then refresh Project Desk. It reuses matching cards, fills missing known
details, restores an archived card, and preserves saved work and drafts. It does
not send instructions to Codex, move the native chat, or execute project work.
The maintained helper is `desk_register.py --input-file <registration.json>`;
the installed skill supplies contextual details and verifies success through the
live desk API. Registration remains available while an older server finishes
long-running reviews, using an atomic merge into the same local database.

Archive project beside Pin hides a project from the main desk without deleting
its files, chats, saved drafts, history, or project record. It does not archive
the native Codex project or stop running work. Open Archived above the cards and
choose Restore project to show it again. Archives persist across imports and
server restarts; pins and project status are retained. While a server upgrade
waits for active reviews to finish, visibility choices are saved in the current
browser and synchronized automatically when the updated server is available.

Review fields autosave as an unsent project draft, including the selected chat, step, reason, and extra instructions. Drafts use revision checks to prevent an older window overwriting a newer save, plus a browser-local recovery copy. Closing or reloading preserves edits. Restoring a draft does not generate over it or send it. Discard draft clears only the draft. Successful queue acknowledgement clears a matching submitted draft; newer edits are retained, and failed sends retain the draft.

Pin projects from their cards to keep them first. Focus list shows pinned projects using the current filters and sort; Show all projects returns to the full list. Pins are stored with project data, and the selected view is remembered in the browser.

Latest Codex reply shows saved final assistant text from the preferred linked local chat (or the most recent linked local chat), with the actual chat title, reply date, and expandable text. Commentary, reasoning, and tool output are excluded. Replies refresh on startup, about every 30 seconds while the server is running, and through the top Refresh button. These reads do not mark work complete or change Last worked on. Visible idle project lists also refresh every five seconds; open forms, expanded details, and selected text are left alone. Cloud chat references remain links rather than automatic local reply sources.

Refresh beside the title updates saved project data without resetting the current search, filters, sort, or theme. Returning focus to the window also refreshes the list when no dialog is open, keeping in-progress form edits intact. Codex index import and connection checks retain their separate controls.

## Development checks

The runtime uses Python's standard library. Install the optional development
packages and browser for UI checks or icon generation:

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Run the full isolated unit test suite from the repository folder:

```powershell
python -m unittest discover -q
```

Focused browser checks start their own temporary servers and databases:

```powershell
python check_setup.py
python check_browser.py
python check_actions.py
python check_audit_send.py
python check_workflow_features.py
python check_smoothness.py
```

These cover first-run setup, project editing, reviewed sends, the searchable
chat picker, audit highlights and new-chat routing, saved drafts, pins, refresh
behavior, and responsive layouts. Normal chat-send checks use mocked transport
and do not send messages to live chats. Recreate icon assets with
`python create_icon.py` only when needed; it writes the generated icon files.

`python check_actions.py --live` is a separate optional test that sends an echo
request to the test chat supplied through `PROJECT_DESK_TEST_CHAT`. Run it only
with permission to message that exact chat. It is not part of the default checks.

## Next-action recommendations and Codex delivery

Click a next action to open its review dialog. Project Desk reads recent messages from the selected existing local chat and asks the signed-in Codex CLI for an ephemeral, read-only recommendation and explanation. You can edit the step and reason and add instructions. Nothing is sent until Send to Codex is clicked. The destination is shown explicitly; the preferred linked chat is selected when available, with an exact workspace-path match as a fallback. You can choose another existing local chat.

Send uses the installed CLI's `codex queue --thread <exact UUID> --message <reviewed text>` command, then opens `codex://threads/<exact UUID>` so the desktop app processes its queue. The app distinguishes a queue acknowledgement from a received message: Received by Codex appears only after the exact user message is found in a new turn in that chat. Receipt reconciliation reads history after slow startup or restart; it never automatically retransmits. Unique request IDs prevent repeat clicks or retries from sending duplicates. Prior matching messages cannot count as new delivery.

The installed Codex CLI and its existing ChatGPT sign-in are required; no separate model API key is used. The destination thread keeps its normal Codex settings. Cloud chats can be opened through their verified links, while automatic recommendation/send targets are local chats. No Codex databases or session files are edited by Project Desk.

Every server startup audits linked local chats with the app-server protocol and canonicalizes their links and titles. Opening a local chat or sending to one revalidates its exact ID. Check chat connections runs the full audit again. Cloud references are shown separately from locally verified chats. Legacy ID repairs are kept in the local metadata so an old snapshot cannot restore a broken ID.

## Desktop setup and local integrations

Desktop access: `Project desk.lnk` starts the local service if needed, waits until it responds, and opens Project desk in a standalone Edge app window (Chrome fallback). It uses a dedicated profile in `data/window-profile` by default; an existing installation can retain its configured browser profile through `data/location.json`. The normal browser profile is left alone. Reopening the shortcut focuses the existing Project desk window when available.

The `Codex (OpenAI).lnk` desktop shortcut runs `Open-CodexWithProjectDesk.ps1`: it opens the separate Project desk window and activates the installed Codex Windows app normally. It does not navigate Codex to a particular chat. The two windows can be moved, resized, and used side by side. This applies to these desktop shortcuts; it is not a system-wide Codex launch hook. No chats are created and no messages are sent.

When the shortcut installer replaces an existing Codex shortcut, it first backs
it up to `data/shortcut-backups/Codex (OpenAI).lnk` unless that backup already
exists. Copy that backup to the desktop to restore the original launcher. The
installer does not create a Windows sign-in startup entry or scheduled monitor.

Custom icon sources are in `assets/project-desk.svg`, `assets/project-desk.png`, and `assets/project-desk.ico`; recreate them with `python create_icon.py`. The desktop icon contains the common Windows sizes from 16 to 256 pixels.

Run `python server.py` or `Start-ProjectDesk.ps1` to start the service. On Windows, `Open-ProjectDesk.ps1` opens the separate app window; the same URL can also be viewed in a browser.

Projects, accepted actions, activity, and manual notes persist in `data/tracker.sqlite3`. Back up the data folder to preserve them. This app runs only on this computer; it is not a cloud sync service.

Codex imports use the saved native-tool export at `data/codex-export.json` plus the existing CMChats `workspace-index.json`. Refresh reads those files; it cannot call Codex's native chat tools itself. The interface shows source timestamps. To obtain fresher native metadata, ask Codex to refresh this app's export using `list_projects` and `list_threads`. No Codex database or conversation is modified. Chat activity includes planning and does not prove a task was completed.

GitHub refresh uses the existing `gh` CLI account and reads the configured repository's latest commit and open issues. It does not change repositories. Automatic suggestions are simple source-based candidates, not an assessment of project priority or completion. Accepting a suggestion or editing a project does not update last-worked time. Use Log activity to record planning or progress manually.

Activity imports normalize timestamps to UTC and retain the newest observation of a chat or commit without adding duplicate entries. Older snapshots cannot replace newer chat details. GitHub network reads happen before merging into the latest saved project, so manual notes or completed actions saved during a refresh are preserved. Local mutations are serialized within the running server. Activity timestamps represent the original work or conversation time; the time a refresh was checked is reported separately.

Manual tracking needs no model API key, public deployment, scheduled task, or
startup registration. Codex features use the installed CLI and its existing
account; account access and usage limits still apply. Launch the local server
again after restarting the computer, or use the installed desktop shortcut.

**Mark done manually** appears when a project has an accepted or manually entered next action. It opens a form with an optional completion note and optional replacement action. Mark done manually saves a permanent completed-action entry, records activity, and updates Last worked on; it does not change project status or blockers. Leaving the replacement empty clears the current action so a new one can be chosen later. Completed actions remain available in each card's history. Cancellation changes nothing; duplicate submissions are idempotent and stale forms cannot complete a changed action.

Project types include Website, App, and Documents Render. Documents Render requires an agency name; the agency field suggests previously saved names and accepts a new name. Agency names also appear on cards and are searchable.

Move chat is available on cards and beside linked chats inside Edit project. It moves the tracker link and its chat activity together and preserves that assignment across saved-index refreshes. It does not move files or change project actions. For destinations backed by a native Codex project, the form can prepare an actual Codex move. The resulting dialog provides an instruction to paste into Codex; the request remains pending until the native `move_thread_to_project` tool succeeds. Destinations created only in the tracker support tracker-only moves. See [AGENTS.md](AGENTS.md) and `python manage_moves.py list` for handling native move requests.
