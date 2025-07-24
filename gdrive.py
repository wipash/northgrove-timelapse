import os
import json
import base64
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, BatchHttpRequest
import io
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

def get_drive_service():
    """Authenticates with Google Drive and returns a service object.
    
    Authentication methods (in order of preference):
    1. Local auth.json file (for local development)
    2. GDRIVE_SA_KEY environment variable (base64-encoded JSON)
    3. GDRIVE_SA_KEY environment variable (plain JSON)
    """
    # Method 1: Try local auth.json file first
    auth_file = Path("auth.json")
    if auth_file.exists():
        try:
            with open(auth_file, 'r') as f:
                creds_json = json.load(f)
            creds = Credentials.from_service_account_info(creds_json, scopes=['https://www.googleapis.com/auth/drive.readonly'])
            service = build('drive', 'v3', credentials=creds)
            print("Using Google Drive credentials from auth.json")
            return service
        except Exception as e:
            print(f"Warning: Failed to load auth.json: {e}")
    
    # Method 2 & 3: Try environment variable
    gdrive_sa_key = os.environ.get("GDRIVE_SA_KEY")
    if not gdrive_sa_key:
        raise ValueError("No Google Drive credentials found. Please create auth.json or set GDRIVE_SA_KEY environment variable.")
    
    # Try to decode as base64 first
    try:
        decoded_key = base64.b64decode(gdrive_sa_key)
        creds_json = json.loads(decoded_key)
        print("Using Google Drive credentials from base64-encoded GDRIVE_SA_KEY")
    except:
        # If base64 decode fails, try as plain JSON
        try:
            creds_json = json.loads(gdrive_sa_key)
            print("Using Google Drive credentials from plain JSON GDRIVE_SA_KEY")
        except json.JSONDecodeError:
            raise ValueError("Failed to parse GDRIVE_SA_KEY. It's not valid JSON or base64-encoded JSON.")
    
    try:
        creds = Credentials.from_service_account_info(creds_json, scopes=['https://www.googleapis.com/auth/drive.readonly'])
        service = build('drive', 'v3', credentials=creds)
        return service
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

def download_file_parallel(service, file_info, temp_dir):
    """Helper function for parallel downloads. Returns the file path on success."""
    try:
        file_path = Path(temp_dir) / file_info['name']
        download_file(service, file_info['id'], file_path)
        return file_path
    except Exception as e:
        print(f"Error downloading {file_info['name']}: {e}")
        return None

def download_files_parallel(service, files, temp_dir, max_workers=10):
    """Downloads multiple files in parallel using thread pool."""
    downloaded_files = []
    
    # Create a thread-local storage for service objects
    thread_local = threading.local()
    
    def get_thread_service():
        # Each thread gets its own service instance to avoid conflicts
        if not hasattr(thread_local, 'service'):
            thread_local.service = get_drive_service()
        return thread_local.service
    
    def download_worker(file_info):
        thread_service = get_thread_service()
        return download_file_parallel(thread_service, file_info, temp_dir)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_file = {executor.submit(download_worker, f): f for f in files}
        
        # Process completed downloads
        for future in as_completed(future_to_file):
            file_info = future_to_file[future]
            try:
                result = future.result()
                if result:
                    downloaded_files.append(result)
            except Exception as e:
                print(f"Download failed for {file_info['name']}: {e}")
    
    return downloaded_files
