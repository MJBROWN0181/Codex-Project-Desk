# Codex Project Desk

Project Desk version 2.0.0 is a local project tracker for software, websites, apps, business work, and document-rendering jobs. It includes completion-driven Codex work queues, project controls, readiness reviews, and a coordinated finishing team alongside saved drafts, pins, latest replies, activity, and dark/light themes.

## Work, queue, and finishing controls

Sending a reviewed next action immediately reserves the project as working. A delivery receipt means the message arrived; completion waits for the exact Codex turn to report completed. While working, project edits and new suggestions are held. Add content saves durable FIFO additions, automatically delivered to the same local chat after completion. The saved final answer updates the card and activity. When the queue is empty, an agent recommends a new step for review; suggestions are never executed automatically. A finished turn does not mean the whole project is complete.

Pause lets the current turn finish and holds queued additions. Resume drains them. Wrap up work schedules a handoff in the same chat after the current turn, then pauses additions. A failed or interrupted turn holds the queue and shows Needs attention. Check work status acknowledges a known failed turn or failed delivery and leaves additions paused for review; ambiguous deliveries are checked without automatic retransmission. Queue receipts and state survive restarts. Interrupted audits/releases are never replayed automatically. Completion checks run about every five seconds; active-chat discovery about every thirty seconds. Local saved Codex history must expose the turn and final status. Cloud chats remain link-only.

Push to GitHub + release commits the project repository's nonignored changes, pushes its current named branch, creates the next annotated patch-version tag, publishes a GitHub release, and verifies publication. This button publishes; it does not create a draft. It validates the configured repository and all push destinations, checks obvious credential files and private keys, rejects behind/diverged branches, and preserves partial progress on failure. No force push, reset, stash, or cleanup is used. A clean unchanged retry resumes its saved incomplete release after checking tag identity. Git and signed-in GitHub CLI access are required. Set the actual local project folder and owner/repository in Edit project first.

Am I done? inspects the actual folder, applies focused required fixes, and reviews again. Finish agent team adds a boss coordinating six specialist reviews: security, errors, writing/AI slop, desktop/mobile UI when applicable, weak spots, and improvements. Specialists inspect independently with at most three running at once; only the boss's repair pass writes files. Existing edits get a local recovery baseline before repairs. Missing access, failed checks, and untested device/authenticated flows stay visible. Agents do not publish, deploy, commit, or send messages as part of reviews. Reports and copyable follow-up prompts are saved locally in data/reports; recovery baselines stay in data/audit-baselines. Review work can take several minutes and progress is shown on the card.

Grades: A ready to use; B almost done and usable; C minor fixes or required features remain; D work in progress and not ready for real use; F not working. A requires supporting checks and no material gaps. Optional improvements alone do not prevent an A. Automated review is bounded to one repair/recheck cycle; unresolved findings stay in the report.

Website projects can have a configured HTTP(S) URL. Up/Down shows the latest bounded HTTP check with its timestamp and response code; checks run roughly once per minute and through Check site. This is a point-in-time check from this computer, not a global uptime guarantee.

## Drafts, focus, and latest replies

Review fields autosave as an unsent project draft, including the selected chat, step, reason, and extra instructions. Drafts use revision checks to prevent an older window overwriting a newer save, plus a browser-local recovery copy. Closing or reloading preserves edits. Restoring a draft does not generate over it or send it. Discard draft clears only the draft. Successful queue acknowledgement clears a matching submitted draft; newer edits are retained, and failed sends retain the draft.

Pin projects from their cards to keep them first. Focus list shows pinned projects using the current filters and sort; Show all projects returns to the full list. Pins are stored with project data, and the selected view is remembered in the browser.

Latest Codex reply shows saved final assistant text from the preferred linked local chat (or the most recent linked local chat), with the actual chat title, reply date, and expandable text. Commentary, reasoning, and tool output are excluded. Replies refresh on startup, about every 30 seconds while the server is running, and through the top Refresh button. These reads do not mark work complete or change Last worked on. Visible idle project lists also refresh every five seconds; open forms, expanded details, and selected text are left alone. Cloud chat references remain links rather than automatic local reply sources.

Refresh beside the title updates saved project data without resetting the current search, filters, sort, or theme. Returning focus to the window also refreshes the list when no dialog is open, keeping in-progress form edits intact. Codex index import and connection checks retain their separate controls.

## Run locally

Python 3.10 or newer is required. Run `python server.py`, then open http://127.0.0.1:8789. The application uses Python's standard library and starts with an empty project list when no local Codex export is available. GitHub refresh additionally uses the already-signed-in `gh` CLI.

Personal state in `data/` is excluded from Git: project records, chat exports, shortcut backups, logs, and the standalone browser profile stay on this computer.

## Checks

Run `python -m unittest -v test_tracker.py` for isolated data tests. For browser checks and icon generation, install `requirements-dev.txt` and Chromium with `python -m playwright install chromium`, then run `python check_browser.py` or `python create_icon.py` as needed.

Run `python -m unittest -v test_tracker.py test_codex_actions.py` for all data and delivery tests. `python check_actions.py` checks the review/send UI using a mock transport and a temporary database. `python check_actions.py --live` is an explicit, optional live test that sends a harmless echo request to this installation's existing integration-test chat; it must not be run against an unrelated account or without permission to message that chat.

`python check_smoothness.py` covers header refresh, retained filters/theme, out-of-order responses, changing a chat target during recommendation generation, receipt-dialog races, and responsive layouts. It uses temporary data and does not send messages.

Run `python -m unittest -v test_tracker.py test_codex_actions.py test_workflow_features.py` for the complete suite. `python check_workflow_features.py` verifies draft and pin persistence through an HTTP-server restart, draft discard, restored chat selection, escaped reply text, and the focus view, with no Codex messages sent.

## Next-action recommendations and Codex delivery

Click a next action to open its review dialog. Project Desk reads recent messages from the selected existing local chat and asks the signed-in Codex CLI for an ephemeral, read-only recommendation and explanation. You can edit the step and reason and add instructions. Nothing is sent until Send to Codex is clicked. The destination is shown explicitly; the preferred linked chat is selected when available, with an exact workspace-path match as a fallback. You can choose another existing local chat.

Send uses the installed CLI's `codex queue --thread <exact UUID> --message <reviewed text>` command, then opens `codex://threads/<exact UUID>` so the desktop app processes its queue. The app distinguishes a queue acknowledgement from a received message: Received by Codex appears only after the exact user message is found in a new turn in that chat. Receipt reconciliation reads history after slow startup or restart; it never automatically retransmits. Unique request IDs prevent repeat clicks or retries from sending duplicates. Prior matching messages cannot count as new delivery.

The installed Codex CLI and its existing ChatGPT sign-in are required; no separate model API key is used. The destination thread keeps its normal Codex settings. Cloud chats can be opened through their verified links, while automatic recommendation/send targets are local chats. No Codex databases or session files are edited by Project Desk.

Every server startup audits linked local chats with the app-server protocol and canonicalizes their links and titles. Opening a local chat or sending to one revalidates its exact ID. Check chat connections runs the full audit again. Cloud references are shown separately from locally verified chats. Legacy ID repairs are kept in the local metadata so an old snapshot cannot restore a broken ID.

## Desktop setup and local integrations

Desktop access: `Project desk.lnk` starts the local service if needed, waits until it responds, and opens Project desk in a standalone Edge app window (Chrome fallback). It uses a dedicated profile in `data/window-profile`, leaving the normal browser profile alone. Reopening the shortcut focuses the existing Project desk window when available.

The `Codex (OpenAI).lnk` desktop shortcut runs `Open-CodexWithProjectDesk.ps1`: it opens the separate Project desk window and activates the installed Codex Windows app normally. It does not navigate Codex to a particular chat. The two windows can be moved, resized, and used side by side. This applies to these desktop shortcuts; it is not a system-wide Codex launch hook. No chats are created and no messages are sent.

The original Codex desktop shortcut is preserved in `data/shortcut-backups/Codex (OpenAI).lnk`. Copy it back to the desktop to restore the original launcher. No Windows sign-in startup entry, taskbar shortcut, or scheduled monitor was installed.

Custom icon sources are in `assets/project-desk.svg`, `assets/project-desk.png`, and `assets/project-desk.ico`; recreate them with `python create_icon.py`. The desktop icon contains the common Windows sizes from 16 to 256 pixels.

Run `python server.py` or `Start-ProjectDesk.ps1` to start the service. On Windows, `Open-ProjectDesk.ps1` opens the separate app window; the same URL can also be viewed in a browser.

Projects, accepted actions, activity, and manual notes persist in `data/tracker.sqlite3`. Back up the data folder to preserve them. This app runs only on this computer; it is not a cloud sync service.

Codex imports use the saved native-tool export at `data/codex-export.json` plus the existing CMChats `workspace-index.json`. Refresh reads those files; it cannot call Codex's native chat tools itself. The interface shows source timestamps. To obtain fresher native metadata, ask Codex to refresh this app's export using `list_projects` and `list_threads`. No Codex database or conversation is modified. Chat activity includes planning and does not prove a task was completed.

GitHub refresh uses the existing `gh` CLI account and reads the configured repository's latest commit and open issues. It does not change repositories. Automatic suggestions are simple source-based candidates, not an assessment of project priority or completion. Accepting a suggestion or editing a project does not update last-worked time. Use Log activity to record planning or progress manually.

Activity imports normalize timestamps to UTC and retain the newest observation of a chat or commit without adding duplicate entries. Older snapshots cannot replace newer chat details. GitHub network reads happen before merging into the latest saved project, so manual notes or completed actions saved during a refresh are preserved. Local mutations are serialized within the running server. Activity timestamps represent the original work or conversation time; the time a refresh was checked is reported separately.

No model API key, payment, public deployment, scheduled task, or startup registration is needed. Launch the local server again after restarting the computer.

Next action done appears when a project has an accepted or manually entered next action. It opens a form with an optional completion note and optional replacement action. Mark done saves a permanent completed-action entry, records activity, and updates Last worked on; it does not change project status or blockers. Leaving the replacement empty clears the current action so a new one can be chosen later. Completed actions remain available in each card's history. Cancellation changes nothing; duplicate submissions are idempotent and stale forms cannot complete a changed action.

Project types include Website, App, and Documents Render. Documents Render requires an agency name; the agency field suggests previously saved names and accepts a new name. Agency names also appear on cards and are searchable.

Move chat is available on cards and beside linked chats inside Edit project. It moves the tracker link and its chat activity together and preserves that assignment across saved-index refreshes. It does not move files or change project actions. For destinations backed by a native Codex project, the form can prepare an actual Codex move. The resulting dialog provides an instruction to paste into Codex; the request remains pending until the native `move_thread_to_project` tool succeeds. Destinations created only in the tracker support tracker-only moves. See AGENTS.md and `python manage_moves.py list` for handling native move requests.
