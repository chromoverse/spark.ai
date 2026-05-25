## Done ✓

### 1. Quota bar below input ✓
- `GET /quota` endpoint returns per-provider key count × free-tier daily limit
- Quota bar shown below chat input chips: "~N req/day · M providers"

### 2A. Tool result summary visible in UI ✓
- The AI verbal summary (what Spark speaks via TTS) is now also emitted as a
  `spark:log` "summary" event → appears as an orange card below tool results
  in the thread view (was previously only spoken, never shown)

### 2B. Confidential action modal (email_send) ✓
- `email_send` (and `message_send`, `whatsapp_send`) trigger an in-app approval
  modal before executing, showing editable To / Subject / Body fields
- User can edit the email then click "Send email", or cancel
- Edited fields are sent back and applied before the tool runs

### 2C. TTS summary timing + shown in UI ✓
- Summary text is now emitted to UI *before* TTS starts streaming, so the user
  sees the response the moment it's ready (no longer text-invisible)
