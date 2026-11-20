# Reviewed paper supervision schedule

Timezone Asia/Kolkata. The existing Codex supervisor checks every five minutes
between 09:00 and 15:55 on Monday, Wednesday, Thursday and Friday. It takes action
only through 15:20 and only within the reviewed calendar coverage. Its first
eligible session is 23 November 2026. The other reviewed sessions are
25, 26 and 27 November. November 24 is a holiday.

At 09:00 it checks whether login is needed. At 09:15 it verifies and may arm the
single reviewed INFY replacement account. At 09:20 it checks the first completed
candle. The entry cutoff is 14:30. Square-off is configured for 15:05, with its
bar completing at 15:10. Final exposure checks occur at 15:15 and 15:20.

The local worker polls every 30 seconds independently of these supervisor checks.
The supervisor does not restart services or create accounts. Faulted runs require
review. Codex, the local app and a valid broker session must be available.
Outside the reviewed calendar it requests a calendar review before activation.
The schedule is local Codex configuration and is not installed by cloning GitHub.
Use the attributed session manifest in infy-paper-calendar-2026-11-20.json.
