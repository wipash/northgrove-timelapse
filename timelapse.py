#!/usr/bin/env python3
"""
Timelapse tool for construction camera images.
Processes daily image folders, creates videos, and uploads to R2.
"""

import os
import json
import yaml
import boto3
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from tqdm import tqdm
import tempfile
import shutil

class TimelapseProcessor:
    def __init__(self, config_path="config.yaml", upload_enabled=True):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        self.state_file = Path("state.json")
        self.state = self.load_state()
        self.upload_enabled = upload_enabled

        # Create output directories
        Path(self.config['output']['videos_dir']).mkdir(exist_ok=True)
        Path(self.config['output']['daily_dir']).mkdir(exist_ok=True)

        # Initialize R2 client (S3 compatible) only if uploads are enabled
        if self.upload_enabled:
            self.s3_client = boto3.client(
                's3',
                endpoint_url=self.config['r2']['endpoint_url'],
                aws_access_key_id=self.config['r2']['access_key_id'],
                aws_secret_access_key=self.config['r2']['secret_access_key']
            )
        else:
            self.s3_client = None

    def load_state(self):
        """Load processing state from file."""
        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {
            'last_processed_date': None,
            'processed_folders': []
        }

    def save_state(self):
        """Save processing state to file."""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def get_daily_folders(self):
        """Get all daily folders sorted by date."""
        source_path = Path(self.config['source']['path'])
        folders = []

        for item in source_path.iterdir():
            if item.is_dir() and item.name.startswith(self.config['source']['folder_pattern']):
                # Extract date from folder name (TLST04A00879_YYMMDDHHMMSS)
                date_str = item.name.split('_')[1][:6]  # YYMMDD
                folders.append({
                    'path': item,
                    'name': item.name,
                    'date': date_str
                })

        # Sort by date
        folders.sort(key=lambda x: x['date'])
        return folders

    def get_images_from_folder(self, folder_path):
        """Get all jpg images from a folder, sorted by name."""
        images = []
        for file in folder_path.iterdir():
            if file.suffix.lower() == '.jpg' and file.name.startswith('TLS_'):
                images.append(file)

        # Sort by filename number
        images.sort(key=lambda x: int(x.stem.split('_')[1]))
        return images

    def create_daily_video(self, folder_info):
        """Create a video from a single day's images."""
        print(f"Processing {folder_info['name']}...")

        images = self.get_images_from_folder(folder_info['path'])
        if not images:
            print(f"  No images found in {folder_info['name']}")
            return None

        # Output path for daily video
        output_path = Path(self.config['output']['daily_dir']) / f"{folder_info['name']}.mp4"

        # Check if this is today's folder (latest folder)
        all_folders = self.get_daily_folders()
        is_today = all_folders and folder_info['name'] == all_folders[-1]['name']

        # Skip if already exists and in processed list, UNLESS it's today's folder
        if output_path.exists() and folder_info['name'] in self.state['processed_folders'] and not is_today:
            print(f"  Daily video already exists, skipping")
            return output_path
        
        if is_today:
            print(f"  Reprocessing today's folder with {len(images)} images")

        # Create video using ffmpeg with image sequence
        # First, create a temporary file list
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            list_file = f.name
            for img in images:
                f.write(f"file '{img}'\n")
                f.write(f"duration 0.033\n")  # 1/30 second per frame
            # Add last image again to ensure it displays
            f.write(f"file '{images[-1]}'\n")

        try:
            cmd = [
                'ffmpeg', '-y',  # Overwrite output
                '-f', 'concat',
                '-safe', '0',
                '-i', list_file,
                '-c:v', self.config['video']['codec'],
                '-preset', self.config['video']['preset'],
                '-crf', str(self.config['video']['crf']),
                '-pix_fmt', 'yuv420p',  # For compatibility
                '-movflags', '+faststart',  # For web streaming
                str(output_path)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  Error creating video: {result.stderr}")
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
            print(f"  Created daily video: {output_path.name}")

            # Update state
            if folder_info['name'] not in self.state['processed_folders']:
                self.state['processed_folders'].append(folder_info['name'])
                self.save_state()

            return output_path

        finally:
            # Clean up temp file
            os.unlink(list_file)

    def create_combined_video(self, video_files, output_name):
        """Combine multiple video files into one."""
        if not video_files:
            return None

        output_path = Path(self.config['output']['videos_dir']) / output_name

        # Create concat list with absolute paths
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            list_file = f.name
            for video in video_files:
                # Ensure we use absolute paths
                abs_path = Path(video).absolute()
                f.write(f"file '{abs_path}'\n")

        try:
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat',
                '-safe', '0',
                '-i', list_file,
                '-c', 'copy',  # Just concatenate, don't re-encode
                str(output_path)
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error combining videos: {result.stderr}")
                # Try to read the concat file for debugging
                with open(list_file, 'r') as f:
                    print(f"Concat file contents:\n{f.read()}")
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
            print(f"Created combined video: {output_name}")
            return output_path

        finally:
            os.unlink(list_file)

    def get_latest_image(self, folders):
        """Get the most recent image from the latest folder."""
        if not folders:
            return None

        # Start from the most recent folder and work backwards
        for folder_info in reversed(folders):
            images = self.get_images_from_folder(folder_info['path'])
            if images:
                return images[-1]  # Last image of the day

        return None

    def upload_to_r2(self, file_path, key):
        """Upload a file to R2."""
        if not self.upload_enabled:
            print(f"Upload disabled: Would upload {key} to R2")
            return
            
        print(f"Uploading {key} to R2...")
        try:
            with open(file_path, 'rb') as f:
                self.s3_client.put_object(
                    Bucket=self.config['r2']['bucket_name'],
                    Key=key,
                    Body=f,
                    ContentType='video/mp4' if file_path.suffix == '.mp4' else 'image/jpeg'
                )
            print(f"  Uploaded successfully")
        except Exception as e:
            print(f"  Upload failed: {e}")

    def process(self, days_limit=None):
        """Main processing function."""
        print("Starting timelapse processing...")

        # Get all daily folders
        folders = self.get_daily_folders()
        
        # Limit to last N days if specified
        if days_limit:
            folders = folders[-days_limit:]
            print(f"Processing last {days_limit} days ({len(folders)} folders)")
        else:
            print(f"Found {len(folders)} daily folders")

        # Process new daily videos
        for folder_info in tqdm(folders, desc="Creating daily videos"):
            self.create_daily_video(folder_info)

        # Get ALL existing daily videos (not just the ones we just created)
        daily_videos_dir = Path(self.config['output']['daily_dir'])
        all_daily_videos = sorted(daily_videos_dir.glob("*.mp4"))
        
        if not all_daily_videos:
            print("No daily videos found to combine")
            return
            
        print(f"\nFound {len(all_daily_videos)} total daily videos")

        # Create full timelapse from ALL daily videos
        print("Creating full timelapse...")
        full_video = self.create_combined_video(all_daily_videos, "timelapse_full.mp4")

        # Create last 7 days video
        print("Creating last 7 days video...")
        recent_videos = all_daily_videos[-7:] if len(all_daily_videos) >= 7 else all_daily_videos
        week_video = self.create_combined_video(recent_videos, "timelapse_week.mp4")

        # Get latest image from ALL folders (not just processed ones)
        all_folders = self.get_daily_folders()
        latest_image = self.get_latest_image(all_folders)

        # Copy latest image to videos directory for easy upload
        if latest_image:
            latest_dest = Path(self.config['output']['videos_dir']) / "latest.jpg"
            shutil.copy2(latest_image, latest_dest)
            print(f"Copied latest image: {latest_image.name}")

        # Upload to R2
        print("\nUploading to R2...")
        if full_video and full_video.exists():
            self.upload_to_r2(full_video, "timelapse/full.mp4")

        if week_video and week_video.exists():
            self.upload_to_r2(week_video, "timelapse/week.mp4")

        if latest_image:
            self.upload_to_r2(latest_dest, "timelapse/latest.jpg")

        print("\nProcessing complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process timelapse images and create videos")
    parser.add_argument('--no-upload', action='store_true', 
                        help='Disable uploads to R2 (for testing)')
    parser.add_argument('--days', type=int, metavar='N',
                        help='Process only the last N days')
    parser.add_argument('--config', default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    
    args = parser.parse_args()
    
    # Create processor with upload setting
    processor = TimelapseProcessor(
        config_path=args.config,
        upload_enabled=not args.no_upload
    )
    
    # Process with optional days limit
    processor.process(days_limit=args.days)
