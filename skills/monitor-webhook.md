# Skill: Monitor → webhook on change

Scrape a page on a schedule with change-tracking on, and fire a webhook when the
content actually changes.

## Steps

1. Baseline scrape with monitoring on (stores a content hash + screenshot).
   ```bash
   curl -X POST $PAWGRAB/scrape \
     -d '{"url": "https://example.com/status", "monitor": true}'
   ```
   The response includes a `diff` with `change_type` (`added`/`removed`/`modified`/`unchanged`).

2. Schedule it to re-run and webhook on change.
   ```bash
   curl -X POST $PAWGRAB/schedule \
     -d '{
       "url": "https://example.com/status",
       "interval_seconds": 900,
       "monitor": true,
       "webhook_url": "https://hooks.example.com/pawgrab"
     }'
   ```

The webhook payload carries the diff summary; a `change_type` of `unchanged` can be
filtered out downstream.
