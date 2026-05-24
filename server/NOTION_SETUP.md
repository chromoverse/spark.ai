# Notion Integration Setup Guide

## What You Can Do

Once connected, Spark can:
- **Search** your Notion workspace for pages and databases
- **Read** page content to answer questions about your notes
- **Create** new pages (with your approval)

## Example Use Cases

```
User: "Search my Notion for project ideas"
→ Spark searches and shows matching pages

User: "What's in my 'Meeting Notes' page?"
→ Spark reads and summarizes the content

User: "Create a task: Buy groceries"
→ Spark creates a new page in your tasks database
```

---

## Setup Steps

### 1. Create Notion Integration

1. Go to https://www.notion.so/my-integrations
2. Click **+ New integration**
3. Fill in:
   - **Name**: Spark AI Assistant
   - **Associated workspace**: Select your workspace
   - **Type**: Internal integration
4. Click **Submit**
5. Copy the **Internal Integration Token** (starts with `secret_`)

### 2. Add to Environment Variables

Add to `server/.env`:

```env
NOTION_CLIENT_ID=your_oauth_client_id
NOTION_CLIENT_SECRET=your_oauth_client_secret
NOTION_REDIRECT_URI=http://localhost:8000/auth/notion/callback
```

**Note:** For OAuth (not just API token), you need to:
1. Go to your integration settings
2. Under **Distribution** → Enable **Public integration**
3. Set **Redirect URI**: `http://localhost:8000/auth/notion/callback`
4. Copy **OAuth client ID** and **OAuth client secret**

### 3. Share Pages with Integration

Notion integrations can only access pages you explicitly share:

1. Open any Notion page you want Spark to access
2. Click **Share** (top right)
3. Search for "Spark AI Assistant"
4. Click **Invite**

**Tip:** Share your top-level workspace page to give access to everything.

### 4. Connect in Spark

1. Start your server: `cd server && python main.py`
2. In your frontend, go to **Settings → Connectors**
3. Click **Connect** on Notion
4. Authorize in the popup
5. Done! ✅

---

## Testing

Test the connection:

```bash
# Search Notion
curl "http://localhost:8000/api/tools/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "notion_search",
    "params": {"query": "meeting", "user_id": "YOUR_USER_ID"}
  }'

# Read a page
curl "http://localhost:8000/api/tools/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "notion_read_page",
    "params": {"page_id": "PAGE_ID", "user_id": "YOUR_USER_ID"}
  }'
```

---

## Available Tools

| Tool | Description | Requires Approval |
|------|-------------|-------------------|
| `notion_search` | Search pages and databases | No |
| `notion_read_page` | Read page content | No |
| `notion_create_page` | Create new page | Yes |

---

## Troubleshooting

### "Integration not found"
- Make sure you shared the page with your integration
- Check integration name matches exactly

### "Unauthorized"
- Verify OAuth credentials in `.env`
- Reconnect via `/auth/notion/connect`

### "Page not found"
- Page ID might be wrong (get from search results)
- Page might not be shared with integration

---

## UI Display

**For your frontend team:**

The connector status should show:

```
Notion
✅ Connected
• Search pages
• Read content  
• Create pages

[Disconnect]
```

When user asks: "Create a task from my emails"

Spark workflow:
1. Read Gmail (via Gmail connector)
2. Extract important emails
3. Create Notion page (via Notion connector)
4. Show user: "Created 3 tasks in Notion: [links]"

**The user sees the result in Notion** - no need to display full content in Spark UI, just confirmation + links.

---

## Next Steps

- Add `notion_query_database` tool (query specific databases)
- Add `notion_update_page` tool (edit existing pages)
- Create skill: "email_to_notion_task" (auto-convert emails to tasks)
