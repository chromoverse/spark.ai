import json
import os

base_dir = r"d:\siddhant-files\projects\ai_assistant\ai_local\tools_plugin"
index_path = os.path.join(base_dir, "registry", "tool_index.json")
manifest_path = os.path.join(base_dir, "manifest.json")

gmail_tools_map = {
    "email_list": ["List emails from the user's mailbox.", "EmailListTool"],
    "email_read": ["Fetch the full content of a single email by message ID.", "EmailReadTool"],
    "email_send": ["Compose and send a new email.", "EmailSendTool"],
    "email_reply": ["Reply to an existing email (stays in the same thread).", "EmailReplyTool"],
    "email_delete": ["Permanently delete an email (bypasses Trash).", "EmailDeleteTool"],
    "email_trash": ["Move an email to the Gmail Trash (recoverable for 30 days).", "EmailTrashTool"],
    "email_mark_read": ["Mark one or more emails as read (removes the UNREAD label).", "EmailMarkReadTool"],
    "email_mark_unread": ["Mark one or more emails as unread (adds the UNREAD label).", "EmailMarkUnreadTool"],
    "email_search": ["Search emails using full Gmail search syntax.", "EmailSearchTool"],
    "email_label": ["Add or remove Gmail labels on an email.", "EmailLabelTool"],
    "email_move": ["Move an email to a different label / folder.", "EmailMoveTool"],
    "email_organize": ["Bulk-organize emails that match a Gmail search query.", "EmailOrganizeTool"],
    "email_labels_list": ["Return all Gmail labels (system + user-created) for the account.", "EmailLabelsListTool"]
}

# Update tool_index.json
with open(index_path, "r", encoding="utf-8") as f:
    index_data = json.load(f)

existing_index_names = {t.get("name") for t in index_data.get("tools", [])}
for name, info in gmail_tools_map.items():
    if name not in existing_index_names:
        index_data["tools"].append({
            "name": name,
            "description": info[0],
            "category": "google",
            "execution_target": "server"
        })

with open(index_path, "w", encoding="utf-8") as f:
    json.dump(index_data, f, indent=2)

# Update manifest.json
with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_data = json.load(f)

existing_manifest_names = {t.get("tool_name") for t in manifest_data.get("plugins", [])}
for name, info in gmail_tools_map.items():
    if name not in existing_manifest_names:
        manifest_data["plugins"].append({
            "tool_name": name,
            "module": "google.gmail",
            "class_name": info[1]
        })

with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest_data, f, indent=2)

print("Added missing Gmail tools to manifest.json and tool_index.json.")
