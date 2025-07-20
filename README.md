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

## What it does

1. Scans the Google Drive folder for daily image folders
2. Creates individual daily videos (only for new days)
3. Combines daily videos into:
   - Full timelapse (beginning to current)
   - Last 7 days video
4. Uploads to R2:
   - `timelapse/full.mp4` - Complete timelapse
   - `timelapse/week.mp4` - Last 7 days
   - `timelapse/day.mp4` - Today's video (latest day)
   - `timelapse/latest.jpg` - Most recent photo

## State tracking

The tool tracks processed folders in `state.json` to avoid reprocessing.
Daily videos are cached in `videos/daily/` for fast concatenation.

## Notes

- Uses existing daily .mp4 files in Google Drive folders if you want to use those instead
- Processes incrementally - only new folders each run
- Videos use H.264 for wide compatibility
- When using `--days`, it still creates the full and 7-day videos from all available daily videos