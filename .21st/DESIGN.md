# Project Desk design context

Project Desk uses plain JavaScript, HTML and CSS with a Python standard-library
server. Preserve its compact project cards, Segoe UI typography, existing color
tokens in `web/style.css`, and light/dark themes.

PDog is the approved project companion: a pearl-white robot dog with floppy
mechanical ears and cyan anime LED expressions. Use the six-pose atlas in
`assets/pdog-poses.png`. Poses represent saved real state, not simulated progress.
Clicking PDog explains state without starting work or changing data. Active work
wins over a queued pause; task completion is separate from project completion.
Keep keyboard focus visible and respect reduced motion.

Card accents follow work state, while audit grades/dates and last-activity age
remain separate. Quiet labels begin after seven idle days. Newly observed
successful tasks get one brief sparkle celebration without moving the card.
