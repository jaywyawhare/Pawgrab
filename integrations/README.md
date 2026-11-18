# Pawgrab integrations

Thin REST wrappers so Pawgrab drops into automation platforms. Each one targets a
running Pawgrab API (`$PAWGRAB_URL`) with a Bearer `$PAWGRAB_API_KEY`.

| Platform | Folder | Status |
|----------|--------|--------|
| n8n | [`n8n/`](./n8n) | Community node (declarative) |
| Zapier | [`zapier/`](./zapier) | App manifest (actions + triggers) |
| Webhooks | use `/schedule` + `engine/webhook.py` | built-in |

All actions are just the documented REST endpoints, so anything the API can do is
reachable from these integrations.
