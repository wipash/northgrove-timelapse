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

    def get_images_from_folder(self, folder_id, temp_dir):
        """
        Lists and downloads images from a GDrive folder into a temporary directory.
        Returns a list of local paths to the downloaded images.
        """
        query = f"'{folder_id}' in parents and mimeType = 'image/jpeg' and name starts with 'TLS_'"
        results = self.drive_service.files().list(q=query, pageSize=1000, fields="files(id, name)").execute()
        files = results.get('files', [])

        if not files:
            return []

        # Use parallel downloads for speed
        print(f"  Downloading {len(files)} images in parallel...")
        downloaded_images = gdrive.download_files_parallel(
            self.drive_service, 
            files, 
            temp_dir,
            max_workers=self.config["download"]["parallel_workers"]
        )

        def safe_sort_key(x):
            try:
                parts = x.stem.split("_")
                if len(parts) >= 2:
                    number_str = "".join(c for c in parts[1].split()[0] if c.isdigit())
                    return int(number_str) if number_str else 0
                return 0
            except:
                return 0

        downloaded_images.sort(key=safe_sort_key)
        return downloaded_images

    def create_daily_video(self, folder_info, is_today=False):
        """Create a video from a single day's images."""
        print(f"Processing {folder_info['name']}...")

        with tempfile.TemporaryDirectory() as temp_dir:
            images = self.get_images_from_folder(folder_info['id'], temp_dir)
            if not images:
                print(f"  No images found in {folder_info['name']}")
                return None

        # Output path for daily video
        output_path = (
            Path(self.config["output"]["daily_dir"]) / f"{folder_info['name']}.mp4"
        )

        # Skip if already exists and in processed list, UNLESS it's today's folder
        if (
            output_path.exists()
            and folder_info["name"] in self.state["processed_folders"]
            and not is_today
        ):
            print("  Daily video already exists, skipping")
            return output_path

        if is_today:
            print(f"  Reprocessing today's folder with {len(images)} images")

        # Create video using ffmpeg with image sequence
        # First, create a temporary file list
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            list_file = f.name
            for img in images:
                f.write(f"file '{img}'\n")
                f.write("duration 0.033\n")  # 1/30 second per frame
            # Add last image again to ensure it displays
            f.write(f"file '{images[-1]}'\n")

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

        # Create concat list with absolute paths
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            list_file = f.name
            for video in video_files:
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
            "total_days": len(all_daily_videos),
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

        # Get all week videos from the videos directory
        videos_dir = Path(self.config["output"]["videos_dir"])
        week_files = list(videos_dir.glob("timelapse_week_*.mp4"))

        for week_file in sorted(week_files):
            # Parse week start date from filename
            week_date_str = week_file.stem.split("_")[
                2
            ]  # YYMMDD from timelapse_week_YYMMDD
            try:
                year = 2000 + int(week_date_str[:2])
                month = int(week_date_str[2:4])
                day = int(week_date_str[4:6])
                week_start = datetime(year, month, day)
                week_end = week_start + timedelta(days=6)

                metadata["weekly_videos"].append(
                    {
                        "filename": week_file.name,
                        "monday_date": week_date_str,
                        "start": week_start.isoformat(),
                        "end": week_end.isoformat(),
                        "r2_path": f"timelapse/weeks/{week_file.name}",
                    }
                )
            except:
                continue

        # Sort weekly videos by date
        metadata["weekly_videos"].sort(key=lambda x: x["monday_date"])

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

    def process(self, days_limit=None, upload_all_weeks=False, build_full=False):
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
        # Determine which folder is "today" (the latest one) to avoid repeated directory scans
        latest_folder_name = folders[-1]["name"] if folders else None

        for folder_info in tqdm(folders, desc="Creating daily videos"):
            is_today = folder_info["name"] == latest_folder_name
            self.create_daily_video(folder_info, is_today=is_today)

        # Get ALL existing daily videos (not just the ones we just created)
        daily_videos_dir = Path(self.config["output"]["daily_dir"])
        all_daily_videos = sorted(daily_videos_dir.glob("*.mp4"))

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

        # Create all week videos
        print("Creating week videos...")
        all_weeks = self.get_all_weeks(all_daily_videos)

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

            # Check if this week's video already exists
            if week_path.exists() and monday_date != current_week_monday:
                print(f"  Week {monday_str} video already exists, skipping")
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
        all_folders = self.get_daily_folders()
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
