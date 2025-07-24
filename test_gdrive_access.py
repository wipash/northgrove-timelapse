#!/usr/bin/env python3
"""Test Google Drive access with service account"""

import gdrive
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv(override=True)

try:
    # Get the drive service
    service = gdrive.get_drive_service()
    print("✓ Successfully authenticated with Google Drive")
    
    # Get the folder ID
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not folder_id:
        print("✗ GDRIVE_FOLDER_ID not set in environment")
        exit(1)
    
    print(f"✓ Using folder ID: {folder_id}")
    
    # Try to list folders
    folders = gdrive.get_folders(service, folder_id)
    
    if folders:
        print(f"✓ Found {len(folders)} folders:")
        for folder in folders[:5]:  # Show first 5
            print(f"  - {folder['name']}")
        if len(folders) > 5:
            print(f"  ... and {len(folders) - 5} more")
    else:
        print("✗ No folders found. This could mean:")
        print("  1. The folder is empty")
        print("  2. The service account doesn't have access")
        print("  3. The folder ID is incorrect")
        
except Exception as e:
    print(f"✗ Error: {e}")
    print("\nTroubleshooting:")
    print("1. Make sure you've shared the Google Drive folder with the service account email")
    print("2. Verify the folder ID is correct")
    print("3. Check that the auth.json file contains valid credentials")