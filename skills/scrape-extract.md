# Skill: Scrape → agent-extract

Pull a structured object out of a page in two steps: scrape it to clean markdown,
then let the agent satisfy a JSON schema from the content.

## Steps

1. Scrape the page.
   ```bash
   curl -X POST $PAWGRAB/scrape \
     -H 'Content-Type: application/json' \
     -d '{"url": "https://example.com/pricing", "formats": ["markdown"]}'
   ```
2. Run the agent with the seed URL and a schema.
   ```bash
   curl -X POST $PAWGRAB/agent \
     -H 'Content-Type: application/json' \
     -d '{
       "prompt": "Extract each pricing tier and its monthly cost.",
       "urls": ["https://example.com/pricing"],
       "effort": "medium",
       "schema": {
         "type": "object",
         "properties": {
           "tiers": {"type": "array", "items": {
             "type": "object",
             "properties": {"name": {"type": "string"}, "monthly_usd": {"type": "number"}}
           }}
         }
       }
     }'
   ```

The agent returns `data`, the `sources` it read, and the `steps` it took.
