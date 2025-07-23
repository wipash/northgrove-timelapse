import os
import json
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

def get_drive_service():
    """Authenticates with Google Drive and returns a service object."""
    gdrive_sa_key = os.environ.get("GDRIVE_SA_KEY")
    if not gdrive_sa_key:
        raise ValueError("GDRIVE_SA_KEY environment variable not set.")

    try:
        creds_json = json.loads(gdrive_sa_key)
        creds = Credentials.from_service_account_info(creds_json, scopes=['https://www.googleapis.com/auth/drive.readonly'])
        service = build('drive', 'v3', credentials=creds)
        return service
    except json.JSONDecodeError:
        raise ValueError("Failed to parse GDRIVE_SA_KEY. It's not valid JSON.")
    except Exception as e:
        raise RuntimeError(f"Failed to create Google Drive service: {e}")

def get_folders(service, folder_id):
    """Lists folders within a given Google Drive folder."""
    query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder'"
    results = service.files().list(
        q=query,
        pageSize=1000,
        fields="nextPageToken, files(id, name)"
    ).execute()
    return results.get('files', [])

def download_file(service, file_id, destination):
    """Downloads a file from Google Drive."""
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()

    with open(destination, 'wb') as f:
        f.write(fh.getvalue())
