# Reviewed paper supervision schedule

Timezone Asia/Kolkata. The existing Codex supervisor checks every five minutes
between 09:00 and 15:55 on Monday, Wednesday, Thursday and Friday. It takes action
only through 15:20 and only within the reviewed calendar coverage. Its first
eligible session is 23 November 2026. The other reviewed sessions are
25, 26 and 27 November. November 24 is a holiday.

At 09:00 it reminds the user about deferred market verification and login.
At 09:15 it may enable automatic stock selection using the reviewed replacement
account only as the assumptions template. That template remains paused.
The selector waits for twenty completed bars. Earliest selection is 10:55, after
which it verifies forward paper decisions on the selected stock.
The entry cutoff is 14:30. Square-off is configured for 15:05, with its bar
completing at 15:10. Final exposure checks occur at 15:15 and 15:20.

The local worker polls every 30 seconds independently of these supervisor checks.
The supervisor does not restart services or create accounts. Faulted runs require
review. Codex, the local app and a valid broker session must be available.
Outside the reviewed calendar it requests a calendar review before activation.
The schedule is local Codex configuration and is not installed by cloning GitHub.
Use the attributed session manifest in infy-paper-calendar-2026-11-20.json.
