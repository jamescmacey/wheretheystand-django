---
title: Hansard update plan
description: Update intervals
aiAssistedGeneration: false
---

## Considerations

Because the Hansard website is behind bot protection it cannot be scraped with simple HTTP requests.  It requires a headless Playwright session which involves, essentially, running Chromium.  Because of the computational overhead associated with this, Hansard updates are not performed by cloud-hosted instances.  Their jobs are sent to a separate Celery queue.

## Search results

Search results are used to build a list of votes, and, in doing so, sitting days that need to be fetched.  The minimum update standards are as follows:

* **For all results from the last seven days:** daily.
* **For all results belonging to the current parliamentary term, or one year prior**: every seven days.
* **For all other results belonging to a previous parliamentary term**: as issues are identified. 

## Dailies

Dailies include the transcript itself, the stylesheet that applies to that transcript, and the structured data.  Dailies are only updated when those dailies are needed to update a vote.

**Before a vote update commences**, a daily will be updated if the daily is older than 23 hours (in the case of a vote occurring in the previous seven days) or 2 days and 23 hours (in the case of any other vote).

## Votes

Votes are updated from the WhereTheyStand copy of Hansard so are necessarily dependend in many respects on the above update cycles.  However, once a vote is known to WhereTheyStand, it will update:
* if a search results update detects that the finishing status of the vote has changed (ie between Draft, Corrected and Final);
* if the vote occurred within the last seven days, daily (as long as the vote is older than 23 hours);
* if the vote's finishing status is not Final, every seven days (as long as the vote is older than 23 hours); and
* never, for all other votes.