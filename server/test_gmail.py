import os
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

def test_list_emails():
    # Load token from file (local only — in prod this comes from DB)
    with open('token.json', 'r') as f:
        token_data = json.load(f)

    creds = Credentials(
        token=token_data['token'],
        refresh_token=token_data['refresh_token'],
        token_uri=token_data['token_uri'],
        client_id=token_data['client_id'],
        client_secret=token_data['client_secret'],
        scopes=token_data['scopes']
    )

    # Auto-refresh if expired
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        print("🔄 Token refreshed")
        # In prod → update access_token in memory cache here

    service = build('gmail', 'v1', credentials=creds)

    # Fetch 10 latest emails
    results = service.users().messages().list(
        userId='me',
        maxResults=10
    ).execute()

    messages = results.get('messages', [])

    if not messages:
        print('No messages found.')
        return

    print(f'📬 Latest {len(messages)} emails:\n')
    for msg in messages:
        detail = service.users().messages().get(
            userId='me',
            id=msg['id'],
            format='metadata',
            metadataHeaders=['From', 'Subject', 'Date']
        ).execute()

        headers = {h['name']: h['value'] for h in detail['payload']['headers']}
        print(f"From    : {headers.get('From', 'N/A')}")
        print(f"Subject : {headers.get('Subject', 'N/A')}")
        print(f"Date    : {headers.get('Date', 'N/A')}")
        print("-" * 50)

if __name__ == "__main__":
    test_list_emails()
