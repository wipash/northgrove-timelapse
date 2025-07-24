#!/usr/bin/env python3
"""
Timelapse tool for construction camera images.
Processes daily image folders, creates videos, and uploads to R2.
"""

import os
import json
import boto3
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from tqdm import tqdm
import tempfile
import gdrive
import io
from googleapiclient.http import MediaIoBaseDownload
import yaml
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)


class TimelapseProcessor:
    def __init__(self, upload_enabled=True):
        self.config = self._load_config_from_env()
        self.state_file = Path("state.json") # This will be managed in R2
        self.upload_enabled = upload_enabled

        # Create output directories
        Path(self.config["output"]["videos_dir"]).mkdir(exist_ok=True)
        Path(self.config["output"]["daily_dir"]).mkdir(exist_ok=True)
        
        # Create image cache directory
        self.image_cache_dir = Path("./videos/images")
        self.image_cache_dir.mkdir(exist_ok=True, parents=True)

        # Initialize R2 client
        if self.upload_enabled:
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=self.config["r2"]["endpoint_url"],
                aws_access_key_id=self.config["r2"]["access_key_id"],
                aws_secret_access_key=self.config["r2"]["secret_access_key"],
            )
        else:
            self.s3_client = None

        self.state = self.load_state()


        # Initialize Google Drive Service
        self.drive_service = gdrive.get_drive_service()

    def _load_config_from_env(self):
        """Loads configuration from environment variables."""
        config = {
            "source": {
                "path": os.environ.get("GDRIVE_FOLDER_ID"),
                "folder_pattern": os.environ.get("FOLDER_PATTERN_PREFIX", "TLST04A00879_"),
            },
            "output": {
                "videos_dir": "./videos",
                "daily_dir": "./videos/daily",
            },
            "r2": {
                "endpoint_url": os.environ.get("R2_ENDPOINT_URL"),
                "access_key_id": os.environ.get("R2_ACCESS_KEY_ID"),
                "secret_access_key": os.environ.get("R2_SECRET_ACCESS_KEY"),
                "bucket_name": os.environ.get("R2_BUCKET_NAME"),
            },
            "video": {
                "fps": int(os.environ.get("VIDEO_FPS", 30)),
                "codec": os.environ.get("VIDEO_CODEC", "libx264"),
                "preset": os.environ.get("VIDEO_PRESET", "slow"),
                "crf": int(os.environ.get("VIDEO_CRF", 28)),
                "max_width": int(os.environ.get("VIDEO_MAX_WIDTH", 1920)),
                "full_video": {
                    "crf": int(os.environ.get("FULL_VIDEO_CRF", 32)),
                    "max_width": int(os.environ.get("FULL_VIDEO_MAX_WIDTH", 1280)),
                    "fps": int(os.environ.get("FULL_VIDEO_FPS", 20)),
                },
            },
            "download": {
                "parallel_workers": int(os.environ.get("DOWNLOAD_WORKERS", 10)),
            },
        }
        if not all([
            config["source"]["path"],
            config["r2"]["endpoint_url"],
            config["r2"]["access_key_id"],
            config["r2"]["secret_access_key"],
            config["r2"]["bucket_name"],
        ]):
            raise ValueError("One or more required environment variables are not set.")
        return config

    def load_state(self):
        """Load processing state from R2."""
        state_key = "state/state.json"
        try:
            response = self.s3_client.get_object(
                Bucket=self.config["r2"]["bucket_name"], Key=state_key
            )
            state_data = response["Body"].read().decode("utf-8")
            return json.loads(state_data)
        except self.s3_client.exceptions.NoSuchKey:
            print("No state file found on R2, starting fresh.")
            return {"last_processed_date": None, "processed_folders": []}
        except Exception as e:
            print(f"Error loading state from R2: {e}")
            # Fallback to a default empty state
            return {"last_processed_date": None, "processed_folders": []}

    def save_state(self):
        """Save processing state to R2."""
        state_key = "state/state.json"
        try:
            self.s3_client.put_object(
                Bucket=self.config["r2"]["bucket_name"],
                Key=state_key,
                Body=json.dumps(self.state, indent=2),
                ContentType="application/json",
            )
        except Exception as e:
            print(f"Error saving state to R2: {e}")

    def get_daily_folders(self):
        """Get all daily folders from Google Drive, sorted by date."""
        gdrive_folders = gdrive.get_folders(self.drive_service, self.config["source"]["path"])
        folders = []

        for item in gdrive_folders:
            if item['name'].startswith(self.config["source"]["folder_pattern"]):
                date_str = item['name'].split("_")[1][:6]
                folders.append({"id": item['id'], "name": item['name'], "date": date_str})

        folders.sort(key=lambda x: x["date"])
        return folders

    def get_images_from_folder(self, folder_id, folder_name):
        """
        Lists and downloads images from a GDrive folder into cache directory.
        Returns a list of local paths to the images (cached or newly downloaded).
        """
        # Use cache directory specific to this folder
        cache_dir = self.image_cache_dir / folder_name
        cache_dir.mkdir(exist_ok=True, parents=True)
        
        query = f"'{folder_id}' in parents and mimeType = 'image/jpeg' and name starts with 'TLS_'"
        results = self.drive_service.files().list(q=query, pageSize=1000, fields="files(id, name)").execute()
        files = results.get('files', [])

        if not files:
            return []

        # Check which files already exist in cache
        cached_files = []
        files_to_download = []
        
        for file in files:
            cached_path = cache_dir / file['name']
            if cached_path.exists():
                cached_files.append(cached_path)
            else:
                files_to_download.append(file)
        
        # Report cache status
        if cached_files:
            print(f"  Using {len(cached_files)} cached images")
        
        # Download only missing files
        if files_to_download:
            print(f"  Downloading {len(files_to_download)} new images...")
            downloaded_images = gdrive.download_files_parallel(
                self.drive_service,
                files_to_download,
                str(cache_dir),
                max_workers=self.config["download"]["parallel_workers"]
            )
            all_images = cached_files + downloaded_images
        else:
            all_images = cached_files

        def safe_sort_key(x):
            try:
                parts = x.stem.split("_")
                if len(parts) >= 2:
                    number_str = "".join(c for c in parts[1].split()[0] if c.isdigit())
                    return int(number_str) if number_str else 0
                return 0
            except:
                return 0

        all_images.sort(key=safe_sort_key)
        return all_images

    def create_daily_video(self, folder_info, is_today=False):
        """Create a video from a single day's images."""
        print(f"Processing {folder_info['name']}...")

        # Output path for daily video
        output_path = (
            Path(self.config["output"]["daily_dir"]) / f"{folder_info['name']}.mp4"
        )

        # R2 cache key for this daily video
        r2_cache_key = f"cache/daily/{folder_info['name']}.mp4"

        # Check local cache first (unless it's today's folder which we always reprocess)
        if output_path.exists() and not is_today:
            print(f"  Using cached local daily video: {output_path.name}")
            # Update state to mark as processed
            if folder_info["name"] not in self.state["processed_folders"]:
                self.state["processed_folders"].append(folder_info["name"])
                self.save_state()
            return output_path

        # If not local, check R2 cache
        if not is_today and self.check_r2_exists(r2_cache_key):
            print(f"  Found in R2 cache, downloading...")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if self.download_from_r2(r2_cache_key, output_path):
                print(f"  Downloaded from cache: {output_path.name}")
                # Update state to mark as processed
                if folder_info["name"] not in self.state["processed_folders"]:
                    self.state["processed_folders"].append(folder_info["name"])
                    self.save_state()
                return output_path
            else:
                print("  Cache download failed, will recreate video")

        # Get images from cache or download if needed
        images = self.get_images_from_folder(folder_info['id'], folder_info['name'])
        if not images:
            print(f"  No images found in {folder_info['name']}")
            return None

        if is_today:
            print(f"  Reprocessing today's folder with {len(images)} images")

        # Create video using ffmpeg with image sequence
        # First, create a temporary file list
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            list_file = f.name
            for img in images:
                # Use absolute path for ffmpeg
                abs_path = Path(img).resolve()
                f.write(f"file '{abs_path}'\n")
                f.write("duration 0.033\n")  # 1/30 second per frame
            # Add last image again to ensure it displays
            abs_path = Path(images[-1]).resolve()
            f.write(f"file '{abs_path}'\n")

        try:
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_file,
                "-c:v",
                self.config["video"]["codec"],
                "-preset",
                self.config["video"]["preset"],
                "-crf",
                str(self.config["video"]["crf"]),
                "-pix_fmt",
                "yuv420p",  # For compatibility
                "-movflags",
                "+faststart",  # For web streaming
            ]

            # Add scaling filter if max_width is specified
            if "max_width" in self.config["video"]:
                max_width = self.config["video"]["max_width"]
                # Scale down only if wider than max_width, maintaining aspect ratio
                cmd.extend(["-vf", f"scale={max_width}:-2:flags=lanczos"])

            # Add bitrate limit if specified (optional, CRF usually better)
            if "bitrate" in self.config["video"]:
                cmd.extend(["-b:v", self.config["video"]["bitrate"]])

            cmd.append(str(output_path))

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  Error creating video: {result.stderr}")
                raise subprocess.CalledProcessError(
                    result.returncode, cmd, result.stdout, result.stderr
                )
            print(f"  Created daily video: {output_path.name}")

            # Upload to R2 cache (except for today's video which changes frequently)
            if not is_today:
                self.upload_to_r2(output_path, r2_cache_key)

            # Update state
            if folder_info["name"] not in self.state["processed_folders"]:
                self.state["processed_folders"].append(folder_info["name"])
                self.save_state()

            return output_path

        finally:
            # Clean up temp file
            os.unlink(list_file)

    def create_combined_video(
        self, video_files, output_name, use_full_compression=False
    ):
        """Combine multiple video files into one."""
        if not video_files:
            return None

        output_path = Path(self.config["output"]["videos_dir"]) / output_name

        # Ensure all video files exist locally (download from R2 if needed)
        available_videos = []
        for video in video_files:
            video_path = Path(video)
            if not video_path.exists():
                # Try to download from R2 cache
                r2_cache_key = f"cache/daily/{video_path.name}"
                if self.check_r2_exists(r2_cache_key):
                    print(f"  Downloading {video_path.name} from cache...")
                    video_path.parent.mkdir(parents=True, exist_ok=True)
                    if self.download_from_r2(r2_cache_key, video_path):
                        available_videos.append(video_path)
                    else:
                        print(f"  Warning: Could not download {video_path.name}")
                else:
                    print(f"  Warning: {video_path.name} not found locally or in cache")
            else:
                available_videos.append(video_path)

        if not available_videos:
            print("  No videos available for combining")
            return None

        # Create concat list with absolute paths
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            list_file = f.name
            for video in available_videos:
                # Ensure we use absolute paths
                abs_path = Path(video).absolute()
                f.write(f"file '{abs_path}'\n")

        try:
            if use_full_compression and "full_video" in self.config["video"]:
                # Re-encode with higher compression for full video
                full_config = self.config["video"]["full_video"]
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    list_file,
                    "-c:v",
                    self.config["video"]["codec"],
                    "-preset",
                    self.config["video"]["preset"],
                    "-crf",
                    str(full_config.get("crf", self.config["video"]["crf"])),
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                ]

                # Add scaling for full video
                if "max_width" in full_config:
                    max_width = full_config["max_width"]
                    cmd.extend(["-vf", f"scale={max_width}:-2:flags=lanczos"])

                # Add framerate adjustment for full video
                if "fps" in full_config:
                    fps = full_config["fps"]
                    cmd.extend(["-r", str(fps)])

                cmd.append(str(output_path))
            else:
                # Just concatenate without re-encoding (for week videos)
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    list_file,
                    "-c",
                    "copy",  # Just concatenate, don't re-encode
                    str(output_path),
                ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"Error combining videos: {result.stderr}")
                # Try to read the concat file for debugging
                with open(list_file, "r") as f:
                    print(f"Concat file contents:\n{f.read()}")
                raise subprocess.CalledProcessError(
                    result.returncode, cmd, result.stdout, result.stderr
                )
            print(f"Created combined video: {output_name}")
            return output_path

        finally:
            os.unlink(list_file)

    def get_latest_image(self, folders):
        """Get the most recent image from the latest folder."""
        if not folders:
            return None, None

        # Start from the most recent folder and work backwards
        for folder_info in reversed(folders):
            query = f"'{folder_info['id']}' in parents and mimeType = 'image/jpeg' and name starts with 'TLS_'"
            results = self.drive_service.files().list(q=query, pageSize=1, orderBy="name desc", fields="files(id, name)").execute()
            files = results.get('files', [])

            if files:
                latest_file = files[0]
                image_id = latest_file['id']

                request = self.drive_service.files().get_media(fileId=image_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()

                return fh.getvalue(), latest_file['name']

        return None, None

    def get_all_weeks(self, all_videos):
        """Get all videos grouped by week (Monday to Sunday)."""
        if not all_videos:
            return {}

        # Parse dates from video filenames
        videos_with_dates = []
        for video in all_videos:
            # Extract date from filename like TLST04A00879_250720070000.mp4
            date_str = video.stem.split("_")[1][:6]  # YYMMDD
            try:
                # Parse date
                year = 2000 + int(date_str[:2])
                month = int(date_str[2:4])
                day = int(date_str[4:6])
                date = datetime(year, month, day)
                videos_with_dates.append((video, date))
            except:
                continue

        if not videos_with_dates:
            return {}

        # Group videos by week
        weeks = {}
        for video, date in videos_with_dates:
            # Find Monday of this date's week
            days_since_monday = date.weekday()  # Monday = 0, Sunday = 6
            monday = date - timedelta(days=days_since_monday)

            if monday not in weeks:
                weeks[monday] = []
            weeks[monday].append(video)

        # Sort videos within each week
        for monday, videos in weeks.items():
            videos.sort(key=lambda v: v.stem)

        return weeks

    def load_events(self):
        """Load interesting events from events.yaml if it exists."""
        events_file = Path("events.yaml")
        if not events_file.exists():
            return []

        try:
            with open(events_file, "r") as f:
                data = yaml.safe_load(f)
                events = data.get("events", [])

            # Process each event to add monday_date
            processed_events = []
            for event in events:
                if "date" in event:
                    # Convert date string to datetime if needed
                    if isinstance(event["date"], str):
                        event_date = datetime.fromisoformat(event["date"])
                    else:
                        event_date = event["date"]

                    # Calculate the Monday of the week containing this event
                    days_since_monday = event_date.weekday()  # Monday = 0, Sunday = 6
                    monday = event_date - timedelta(days=days_since_monday)

                    # Format monday_date as YYMMDD to match video filename format
                    monday_str = monday.strftime("%y%m%d")

                    processed_event = {
                        "title": event.get("title", ""),
                        "date": event_date.isoformat(),
                        "monday_date": monday_str,
                    }

                    if "description" in event:
                        processed_event["description"] = event["description"]

                    processed_events.append(processed_event)

            return processed_events
        except Exception as e:
            print(f"Warning: Failed to load events.yaml: {e}")
            return []

    def generate_metadata(self, all_daily_videos, week_video, latest_image_filename):
        """Generate metadata JSON for web frontend."""
        metadata = {
            "last_updated": datetime.now().isoformat(),
            "total_days": 0,  # Will be calculated after we process weekly videos
            "latest_image": None,
            "latest_day": None,
            "current_week": None,
            "weekly_videos": [],
            "date_range": {"start": None, "end": None},
            "events": self.load_events(),
        }

        if all_daily_videos:
            # Parse dates from video filenames
            dates = []
            for video in all_daily_videos:
                date_str = video.stem.split("_")[1][:6]  # YYMMDD
                try:
                    year = 2000 + int(date_str[:2])
                    month = int(date_str[2:4])
                    day = int(date_str[4:6])
                    date = datetime(year, month, day)
                    dates.append(date)
                except:
                    continue

            if dates:
                dates.sort()
                metadata["date_range"]["start"] = dates[0].isoformat()
                metadata["date_range"]["end"] = dates[-1].isoformat()
                metadata["latest_day"] = dates[-1].isoformat()

        if latest_image_filename:
            # The filename itself doesn't have date info, so we use the latest day from videos
            if metadata["latest_day"]:
                metadata["latest_image"] = {
                    "date": metadata["latest_day"],
                    "filename": latest_image_filename,
                }

        if week_video:
            # Parse week start date from filename
            week_date_str = week_video.stem.split("_")[
                2
            ]  # YYMMDD from timelapse_week_YYMMDD
            try:
                year = 2000 + int(week_date_str[:2])
                month = int(week_date_str[2:4])
                day = int(week_date_str[4:6])
                week_start = datetime(year, month, day)
                # Week end is 6 days later
                week_end = week_start + timedelta(days=6)
                metadata["current_week"] = {
                    "start": week_start.isoformat(),
                    "end": week_end.isoformat(),
                    "monday_date": week_date_str,
                }
            except:
                pass

        # Get all week videos from R2 storage (local files should already be uploaded)
        r2_week_keys = self.list_r2_keys("timelapse/weeks/")
        r2_week_filenames = [k.split('/')[-1] for k in r2_week_keys if k.endswith('.mp4') and 'timelapse_week_' in k]

        for week_filename in sorted(r2_week_filenames):
            # Parse week start date from filename
            try:
                week_date_str = week_filename.split("_")[2].split(".")[0]  # YYMMDD from timelapse_week_YYMMDD.mp4
                year = 2000 + int(week_date_str[:2])
                month = int(week_date_str[2:4])
                day = int(week_date_str[4:6])
                week_start = datetime(year, month, day)
                week_end = week_start + timedelta(days=6)

                metadata["weekly_videos"].append(
                    {
                        "filename": week_filename,
                        "monday_date": week_date_str,
                        "start": week_start.isoformat(),
                        "end": week_end.isoformat(),
                        "r2_path": f"timelapse/weeks/{week_filename}",
                    }
                )
            except:
                continue

        # Sort weekly videos by date
        metadata["weekly_videos"].sort(key=lambda x: x["monday_date"])
        
        # Calculate total_days as days since the start of the first weekly video
        if metadata["weekly_videos"]:
            first_week_start = datetime.fromisoformat(metadata["weekly_videos"][0]["start"])
            today = datetime.now().date()
            metadata["total_days"] = (today - first_week_start.date()).days + 1

        return metadata

    def upload_to_r2(self, file_path, key):
        """Upload a file to R2."""
        if not self.upload_enabled:
            print(f"Upload disabled: Would upload {key} to R2")
            return

        print(f"Uploading {key} to R2...")
        try:
            with open(file_path, "rb") as f:
                self.s3_client.put_object(
                    Bucket=self.config["r2"]["bucket_name"],
                    Key=key,
                    Body=f,
                    ContentType="video/mp4"
                    if file_path.suffix == ".mp4"
                    else "image/jpeg",
                )
            print("  Uploaded successfully")
        except Exception as e:
            print(f"  Upload failed: {e}")

    def check_r2_exists(self, key):
        """Check if a file exists in R2."""
        if not self.upload_enabled:
            return False

        try:
            self.s3_client.head_object(
                Bucket=self.config["r2"]["bucket_name"],
                Key=key
            )
            return True
        except self.s3_client.exceptions.NoSuchKey:
            return False
        except Exception as e:
            print(f"Error checking R2 existence for {key}: {e}")
            return False

    def download_from_r2(self, key, local_path):
        """Download a file from R2 to local path."""
        if not self.upload_enabled:
            return False

        try:
            self.s3_client.download_file(
                self.config["r2"]["bucket_name"],
                key,
                str(local_path)
            )
            return True
        except Exception as e:
            print(f"Error downloading {key} from R2: {e}")
            return False

    def delete_from_r2(self, key):
        """Delete a file from R2."""
        if not self.upload_enabled:
            return False

        try:
            self.s3_client.delete_object(
                Bucket=self.config["r2"]["bucket_name"],
                Key=key
            )
            return True
        except Exception as e:
            print(f"Error deleting {key} from R2: {e}")
            return False

    def list_r2_keys(self, prefix):
        """List all keys in R2 with given prefix."""
        if not self.upload_enabled:
            return []

        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.config["r2"]["bucket_name"],
                Prefix=prefix
            )

            if 'Contents' not in response:
                return []

            return [obj['Key'] for obj in response['Contents']]
        except Exception as e:
            print(f"Error listing R2 keys with prefix {prefix}: {e}")
            return []

    def get_all_daily_videos(self):
        """Get list of all daily videos, checking both local and R2."""
        daily_videos_dir = Path(self.config["output"]["daily_dir"])
        daily_videos_dir.mkdir(parents=True, exist_ok=True)

        # Get local videos
        local_videos = {v.name: v for v in daily_videos_dir.glob("*.mp4")}

        # Get R2 cached videos
        r2_daily_keys = self.list_r2_keys("cache/daily/")
        r2_video_names = {k.split('/')[-1]: k for k in r2_daily_keys if k.endswith('.mp4')}

        # Combine both sources, preferring local if exists
        all_video_names = set(local_videos.keys()) | set(r2_video_names.keys())

        # Sort by name (which includes date)
        sorted_names = sorted(all_video_names)

        # Return paths (local if exists, otherwise will be downloaded when needed)
        video_paths = []
        for name in sorted_names:
            if name in local_videos:
                video_paths.append(local_videos[name])
            else:
                # Return path where it would be if downloaded
                video_paths.append(daily_videos_dir / name)

        return video_paths

    def cleanup_old_daily_videos(self, current_week_monday):
        """Remove daily videos from R2 cache for weeks that have been compiled."""
        if not self.upload_enabled or not current_week_monday:
            return

        print("\nCleaning up old daily videos from R2 cache...")
        deleted_count = 0

        # List all daily videos in R2 cache
        r2_daily_keys = self.list_r2_keys("cache/daily/")

        for r2_key in r2_daily_keys:
            if not r2_key.endswith('.mp4'):
                continue

            # Parse date from video filename
            video_name = r2_key.split('/')[-1].replace('.mp4', '')
            date_str = video_name.split("_")[1][:6]  # YYMMDD
            try:
                year = 2000 + int(date_str[:2])
                month = int(date_str[2:4])
                day = int(date_str[4:6])
                video_date = datetime(year, month, day)

                # Get the Monday of this video's week
                days_since_monday = video_date.weekday()
                video_monday = video_date - timedelta(days=days_since_monday)

                # If this video is from a past week (not current week)
                if video_monday < current_week_monday:
                    # Check if weekly video exists before deleting daily
                    week_monday_str = video_monday.strftime("%y%m%d")
                    week_r2_key = f"timelapse/weeks/timelapse_week_{week_monday_str}.mp4"

                    if self.check_r2_exists(week_r2_key):
                        # Weekly video exists, safe to delete daily
                        if self.delete_from_r2(r2_key):
                            deleted_count += 1
                            if deleted_count <= 5:  # Show first few deletions
                                print(f"  Deleted {video_name}.mp4 (week {week_monday_str} compiled)")

            except Exception as e:
                print(f"  Warning: Could not process {video_name}: {e}")

        if deleted_count > 5:
            print(f"  ... and {deleted_count - 5} more daily videos")

        print(f"  Total daily videos cleaned up: {deleted_count}")

    def cleanup_local_cache(self, max_age_days=14):
        """Remove cached images and daily videos older than max_age_days."""
        now = datetime.now()
        cutoff_date = now - timedelta(days=max_age_days)
        
        # Clean up old image cache
        if self.image_cache_dir.exists():
            print(f"\nCleaning up image cache older than {max_age_days} days...")
            deleted_image_count = 0
            
            for folder_dir in self.image_cache_dir.iterdir():
                if not folder_dir.is_dir():
                    continue
                    
                # Parse date from folder name (e.g., TLST04A00879_250721065959)
                try:
                    date_str = folder_dir.name.split("_")[1][:6]  # YYMMDD
                    year = 2000 + int(date_str[:2])
                    month = int(date_str[2:4])
                    day = int(date_str[4:6])
                    folder_date = datetime(year, month, day)
                    
                    if folder_date < cutoff_date:
                        # Remove entire folder
                        import shutil
                        shutil.rmtree(folder_dir)
                        deleted_image_count += 1
                        if deleted_image_count <= 3:  # Show first few deletions
                            print(f"  Removed old image cache: {folder_dir.name}")
                            
                except Exception as e:
                    print(f"  Warning: Could not process {folder_dir.name}: {e}")
            
            if deleted_image_count > 3:
                print(f"  ... and {deleted_image_count - 3} more folders")
            
            print(f"  Total image cache folders cleaned up: {deleted_image_count}")
        
        # Clean up old daily videos from local cache
        daily_dir = Path(self.config["output"]["daily_dir"])
        if daily_dir.exists():
            print(f"\nCleaning up local daily videos older than {max_age_days} days...")
            deleted_video_count = 0
            
            for video_path in daily_dir.glob("*.mp4"):
                # Parse date from video filename
                try:
                    date_str = video_path.stem.split("_")[1][:6]  # YYMMDD
                    year = 2000 + int(date_str[:2])
                    month = int(date_str[2:4])
                    day = int(date_str[4:6])
                    video_date = datetime(year, month, day)
                    
                    if video_date < cutoff_date:
                        video_path.unlink()
                        deleted_video_count += 1
                        if deleted_video_count <= 3:
                            print(f"  Removed old daily video: {video_path.name}")
                            
                except Exception as e:
                    print(f"  Warning: Could not process {video_path.name}: {e}")
            
            if deleted_video_count > 3:
                print(f"  ... and {deleted_video_count - 3} more videos")
                
            print(f"  Total local daily videos cleaned up: {deleted_video_count}")
        
        # Clean up ALL weekly videos from local cache (they're regenerated from scratch)
        videos_dir = Path(self.config["output"]["videos_dir"])
        if videos_dir.exists():
            print(f"\nCleaning up all local weekly videos (regenerated fresh each run)...")
            deleted_week_count = 0
            
            for week_path in videos_dir.glob("timelapse_week_*.mp4"):
                try:
                    week_path.unlink()
                    deleted_week_count += 1
                    if deleted_week_count <= 3:
                        print(f"  Removed weekly video: {week_path.name}")
                        
                except Exception as e:
                    print(f"  Warning: Could not remove {week_path.name}: {e}")
            
            if deleted_week_count > 3:
                print(f"  ... and {deleted_week_count - 3} more videos")
                
            print(f"  Total local weekly videos cleaned up: {deleted_week_count}")

    def process(self, days_limit=None, upload_all_weeks=False, build_full=False):
        """Main processing function."""
        print("Starting timelapse processing...")

        # Get all daily folders
        all_folders = self.get_daily_folders()

        # Determine which folder is "today" from ALL folders (not limited set)
        latest_folder_name = all_folders[-1]["name"] if all_folders else None

        # For efficiency, limit processing to recent days, but ensure current week is complete
        if days_limit:
            # Start with the requested limit
            folders_to_process = all_folders[-days_limit:]

            # But also ensure we have all days needed for current week compilation
            if all_folders:
                # Get current week date range
                latest_date_str = latest_folder_name.split("_")[1][:6]  # YYMMDD
                try:
                    year = 2000 + int(latest_date_str[:2])
                    month = int(latest_date_str[2:4])
                    day = int(latest_date_str[4:6])
                    latest_date = datetime(year, month, day)

                    # Find Monday of current week
                    days_since_monday = latest_date.weekday()
                    current_week_monday = latest_date - timedelta(days=days_since_monday)

                    # Ensure we process all days from current week Monday onwards
                    current_week_folders = []
                    for folder in all_folders:
                        folder_date_str = folder["name"].split("_")[1][:6]
                        try:
                            folder_year = 2000 + int(folder_date_str[:2])
                            folder_month = int(folder_date_str[2:4])
                            folder_day = int(folder_date_str[4:6])
                            folder_date = datetime(folder_year, folder_month, folder_day)

                            if folder_date >= current_week_monday:
                                current_week_folders.append(folder)
                        except:
                            continue

                    # Combine recent days + current week days (removes duplicates)
                    folder_names_to_process = set(f["name"] for f in folders_to_process)
                    folder_names_to_process.update(f["name"] for f in current_week_folders)

                    # Rebuild folders list maintaining order
                    folders = [f for f in all_folders if f["name"] in folder_names_to_process]

                except:
                    # Fallback to original behavior if date parsing fails
                    folders = folders_to_process
            else:
                folders = folders_to_process

            print(f"Processing {len(folders)} folders (including current week completion)")
        else:
            folders = all_folders
            print(f"Found {len(all_folders)} daily folders")

        # Track which videos were processed this run (vs pulled from cache)
        processed_this_run = set()
        
        for folder_info in tqdm(folders, desc="Creating daily videos"):
            is_today = folder_info["name"] == latest_folder_name
            daily_video = self.create_daily_video(folder_info, is_today=is_today)
            if daily_video:
                processed_this_run.add(daily_video.stem)

        # Get ALL existing daily videos from both local and R2
        all_daily_videos = self.get_all_daily_videos()

        if not all_daily_videos:
            print("No daily videos found to combine")
            return

        print(f"\nFound {len(all_daily_videos)} total daily videos")

        # Create full timelapse from ALL daily videos with extra compression
        full_video = None
        if build_full:
            print("Creating full timelapse...")
            full_video = self.create_combined_video(
                all_daily_videos, "timelapse_full.mp4", use_full_compression=True
            )
        else:
            print("Skipping full timelapse (use --build-full to create it)")

        # Create week videos - be smart about which weeks to process
        print("Creating week videos...")
        
        # Determine processing mode based on days_limit
        if days_limit and days_limit < 30:  # Ephemeral mode (small limit)
            # Only process weeks that contain videos we actually processed this run
            relevant_daily_videos = [v for v in all_daily_videos if Path(v).stem in processed_this_run]
            all_weeks = self.get_all_weeks(relevant_daily_videos)
            print(f"  Ephemeral mode: Only checking {len(all_weeks)} relevant weeks")
        else:  # Local/recovery mode (no limit or large limit)
            # Process all weeks for full regeneration capability
            all_weeks = self.get_all_weeks(all_daily_videos)
            print(f"  Full mode: Checking {len(all_weeks)} total weeks")

        # Find the current week for special handling
        current_week_monday = None
        if all_weeks:
            # The last week is the current week
            current_week_monday = max(all_weeks.keys())

        week_video = None  # This will be the current week video
        week_videos_to_upload = []  # Track all weeks if upload_all_weeks is True

        for monday_date, week_videos in all_weeks.items():
            # Create filename based on Monday's date
            monday_str = monday_date.strftime("%y%m%d")
            week_filename = f"timelapse_week_{monday_str}.mp4"
            week_path = Path(self.config["output"]["videos_dir"]) / week_filename
            week_r2_key = f"timelapse/weeks/{week_filename}"

            # For past weeks, check R2 first
            if monday_date != current_week_monday and self.check_r2_exists(week_r2_key):
                print(f"  Week {monday_str} video exists in R2, skipping creation")
                # Download it if we need it locally and uploading all weeks
                if upload_all_weeks and not week_path.exists():
                    week_path.parent.mkdir(parents=True, exist_ok=True)
                    if self.download_from_r2(week_r2_key, week_path):
                        week_videos_to_upload.append(week_path)
                continue

            # Check if this week's video already exists locally
            if week_path.exists() and monday_date != current_week_monday:
                print(f"  Week {monday_str} video already exists locally, skipping")
                if upload_all_weeks:
                    week_videos_to_upload.append(week_path)
                continue

            print(f"  Creating week {monday_str} video ({len(week_videos)} days)")
            created_video = self.create_combined_video(week_videos, week_filename)

            if created_video:
                # Keep track of current week video for upload
                if monday_date == current_week_monday:
                    week_video = created_video

                # Add to upload list if uploading all weeks
                if upload_all_weeks:
                    week_videos_to_upload.append(created_video)

        # Get latest image from ALL folders (not just processed ones)
        latest_image_data, latest_image_filename = self.get_latest_image(all_folders)

        latest_dest = None
        if latest_image_data:
            latest_dest = Path(self.config["output"]["videos_dir"]) / "latest.jpg"
            with open(latest_dest, "wb") as f:
                f.write(latest_image_data)
            print(f"Saved latest image: {latest_image_filename}")

        # Upload to R2
        print("\nUploading to R2...")
        if full_video and full_video.exists():
            self.upload_to_r2(full_video, "timelapse/full.mp4")
        elif build_full and not full_video:
            print("Full video was requested but not created successfully")

        if week_video and week_video.exists():
            # Upload with unique week name and also as current week
            week_key = f"timelapse/weeks/{week_video.stem}.mp4"
            self.upload_to_r2(week_video, week_key)
            self.upload_to_r2(week_video, "timelapse/week.mp4")

        if latest_dest and latest_dest.exists():
            self.upload_to_r2(latest_dest, "timelapse/latest.jpg")

        # Upload the latest day's video
        if all_daily_videos:
            latest_day_video = all_daily_videos[-1]
            self.upload_to_r2(latest_day_video, "timelapse/day.mp4")

        # Upload all historical week videos if requested
        if upload_all_weeks and week_videos_to_upload:
            print(f"\nUploading {len(week_videos_to_upload)} historical week videos...")
            for week_video_path in week_videos_to_upload:
                week_key = f"timelapse/weeks/{week_video_path.stem}.mp4"
                self.upload_to_r2(week_video_path, week_key)

        # Generate and upload metadata for web frontend
        print("\nGenerating metadata...")
        metadata = self.generate_metadata(all_daily_videos, week_video, latest_image_filename)

        # Save metadata locally and upload
        metadata_path = Path(self.config["output"]["videos_dir"]) / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        self.upload_to_r2(metadata_path, "timelapse/metadata.json")

        # Clean up old daily videos from R2 cache (only if we have a current week)
        if current_week_monday and self.upload_enabled:
            self.cleanup_old_daily_videos(current_week_monday)
        
        # Clean up old local cache (images and daily videos)
        if days_limit and days_limit < 30:  # Only cleanup in ephemeral mode
            self.cleanup_local_cache(max_age_days=14)

        print("\nProcessing complete!")


def main():
    parser = argparse.ArgumentParser(
        description="Process timelapse images and create videos"
    )
    parser.add_argument(
        "--no-upload", action="store_true", help="Disable uploads to R2 (for testing)"
    )
    parser.add_argument(
        "--days", type=int, metavar="N", help="Process only the last N days"
    )
    parser.add_argument(
        "--upload-all-weeks",
        action="store_true",
        help="Upload all historical week videos to R2 (not just current week)",
    )
    parser.add_argument(
        "--build-full",
        action="store_true",
        help="Build the full timelapse video (can be slow and large)",
    )

    args = parser.parse_args()

    # Create processor with upload setting
    processor = TimelapseProcessor(upload_enabled=not args.no_upload)

    # Process with optional days limit and upload settings
    processor.process(
        days_limit=args.days,
        upload_all_weeks=args.upload_all_weeks,
        build_full=args.build_full,
    )

if __name__ == "__main__":
    main()
