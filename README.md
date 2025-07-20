# Northgrove Timelapse Tool

Processes construction camera images and creates timelapse videos for R2 upload.

## Setup

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Edit `config.yaml`:
   - Add your Cloudflare R2 credentials
   - Adjust video settings if needed

## Usage

Basic usage:
```bash
uv run python timelapse.py
```

### Command Line Options

- `--no-upload` - Disable uploads to R2 (for testing)
- `--days N` - Process only the last N days
- `--config FILE` - Use alternate config file (default: config.yaml)
- `--upload-all-weeks` - Upload all historical week videos to R2 (not just current week)
- `--help` - Show help message

### Examples

Test without uploading:
```bash
uv run python timelapse.py --no-upload
```

Process only the last 2 days:
```bash
uv run python timelapse.py --days 2
```

Test with last 2 days, no upload:
```bash
uv run python timelapse.py --no-upload --days 2
```

Upload all historical week videos:
```bash
uv run python timelapse.py --upload-all-weeks
```

## What it does

1. Scans the Google Drive folder for daily image folders
2. Creates individual daily videos (only for new days)
3. Combines daily videos into:
   - Full timelapse (beginning to current)
   - Current week video (Monday to today)
4. Uploads to R2:
   - `timelapse/full.mp4` - Complete timelapse
   - `timelapse/week.mp4` - Current week (Monday to today)
   - `timelapse/weeks/timelapse_week_YYMMDD.mp4` - Archived weekly videos (named by Monday's date)
   - `timelapse/day.mp4` - Today's video (latest day)
   - `timelapse/latest.jpg` - Most recent photo
   - `timelapse/metadata.json` - Metadata for web frontend (dates, counts, etc.)

## Metadata for Web Frontend

The tool generates `timelapse/metadata.json` with information for your web frontend:

```json
{
  "last_updated": "2025-07-21T10:30:00.123456",
  "total_days": 150,
  "latest_image": {
    "date": "2025-07-21T00:00:00",
    "filename": "TLS_000000144.jpg"
  },
  "latest_day": "2025-07-21T00:00:00",
  "current_week": {
    "start": "2025-07-21T00:00:00",
    "end": "2025-07-27T00:00:00",
    "monday_date": "250721"
  },
  "weekly_videos": [
    {
      "filename": "timelapse_week_250714.mp4",
      "monday_date": "250714",
      "start": "2025-07-14T00:00:00",
      "end": "2025-07-20T00:00:00",
      "r2_path": "timelapse/weeks/timelapse_week_250714.mp4"
    },
    {
      "filename": "timelapse_week_250721.mp4",
      "monday_date": "250721",
      "start": "2025-07-21T00:00:00",
      "end": "2025-07-27T00:00:00",
      "r2_path": "timelapse/weeks/timelapse_week_250721.mp4"
    }
  ],
  "date_range": {
    "start": "2025-02-21T00:00:00",
    "end": "2025-07-21T00:00:00"
  }
}
```

## State tracking

The tool tracks processed folders in `state.json` to avoid reprocessing.
Daily videos are cached in `videos/daily/` for fast concatenation.

## Notes

- Uses existing daily .mp4 files in Google Drive folders if you want to use those instead
- Processes incrementally - only new folders each run
- Videos use H.264 for wide compatibility
- When using `--days`, it still creates the full and week videos from all available daily videos
- The current day's folder is always reprocessed to include new images
- Week videos are created for all weeks from the beginning
- Historical week videos are only uploaded to R2 when using `--upload-all-weeks`