# Codex Project Desk

Project Desk version 1.1.0 is a local project tracker for software, websites, apps, business work, and document-rendering jobs. It offers editable next actions, activity history, completion tracking, GitHub refresh, Codex chat connections, agent recommendations, reviewed message delivery, and a persistent dark/light theme.

## Run locally

Python 3.10 or newer is required. Run `python server.py`, then open http://127.0.0.1:8789. The application uses Python's standard library and starts with an empty project list when no local Codex export is available. GitHub refresh additionally uses the already-signed-in `gh` CLI.

Personal state in `data/` is excluded from Git: project records, chat exports, shortcut backups, logs, and the standalone browser profile stay on this computer.

## Checks

Run `python -m unittest -v test_tracker.py` for isolated data tests. For browser checks and icon generation, install `requirements-dev.txt` and Chromium with `python -m playwright install chromium`, then run `python check_browser.py` or `python create_icon.py` as needed.

Run `python -m unittest -v test_tracker.py test_codex_actions.py` for all data and delivery tests. `python check_actions.py` checks the review/send UI using a mock transport and a temporary database. `python check_actions.py --live` is an explicit, optional live test that sends a harmless echo request to this installation's existing integration-test chat; it must not be run against an unrelated account or without permission to message that chat.

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
