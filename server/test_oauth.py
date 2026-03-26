import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
TOKEN_FILE = 'token.json'
CREDS_FILE = 'credentials.json'

# Check if token already exists
creds = None
if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

# If no valid credentials available, run the flow
if not creds or not creds.valid:
    if not os.path.exists(CREDS_FILE):
        raise FileNotFoundError(f"Client secrets file '{CREDS_FILE}' not found. Please download it from Google Cloud Console.")
    
    # First run: opens browser for user to log in
    flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    
    # Save creds for next run
    with open(TOKEN_FILE, 'w') as f:
        f.write(creds.to_json())

# Build service
service = build('gmail', 'v1', credentials=creds)

# List inbox
results = service.users().messages().list(userId='me', q='is:unread').execute()
messages = results.get('messages', [])

if not messages:
    print('No unread messages found.')
else:
    print(f'Found {len(messages)} unread messages.')
    for msg in messages[:5]:
        print(f'ID: {msg["id"]}')