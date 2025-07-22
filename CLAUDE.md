# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Northgrove Timelapse Tool processes construction camera images and creates timelapse videos. It consists of:
- **Backend**: Python application that processes images, creates videos, and uploads to Cloudflare R2
- **Frontend**: Next.js web viewer deployed to Cloudflare Workers

## Essential Commands

### Backend (Python)
```bash
# Install dependencies
uv sync

# Run timelapse processing
uv run python timelapse.py

# Common options
uv run python timelapse.py --no-upload      # Test without uploading
uv run python timelapse.py --days 2          # Process last 2 days only
uv run python timelapse.py --build-full      # Build full timelapse video
uv run python timelapse.py --upload-all-weeks # Upload historical weeks
```

### Frontend (Next.js)
```bash
cd frontend

# Install dependencies
pnpm install

# Development
pnpm dev

# Build and deploy
pnpm build
pnpm deploy    # Deploy to Cloudflare Workers
pnpm preview   # Test production build locally
```

## Architecture Overview

### Backend Processing Flow
1. **Image Discovery**: Scans Google Drive folders for daily construction images
2. **Video Creation**: Uses FFmpeg to create daily videos (30fps, H.264)
3. **Video Compilation**: Combines daily videos into weekly and full timelapses
4. **Upload**: Uploads videos and metadata to Cloudflare R2
5. **State Tracking**: Maintains state.json to track processed folders

### Frontend Architecture
- **Next.js 15** with App Router pattern
- **Server Components** for initial data fetching
- **Client Components** for video player and navigation
- **Cloudflare Workers** deployment via OpenNext
- Fetches metadata.json from R2 to display available videos

### R2 Storage Structure
```
timelapse/
├── full.mp4                    # Complete project timelapse
├── week.mp4                    # Current week timelapse
├── day.mp4                     # Today's video
├── weeks/
│   └── timelapse_week_*.mp4    # Historical weekly videos
├── latest.jpg                  # Most recent construction photo
└── metadata.json               # Video metadata for frontend
```

## Key Configuration

### Backend (config.yaml)
- Copy from config-example.yaml
- Set source_path for image location
- Configure R2 credentials (endpoint, access_key, secret_key, bucket)
- Video settings: fps, codec, resolution

### Frontend Environment
- R2 base URL: https://nthgrv.mcgrath.nz/timelapse
- No environment variables needed (public R2 bucket)

## Events System

### events.yaml Configuration
Create/edit `events.yaml` to track interesting construction milestones:

```yaml
events:
  - title: "Roof Installation"
    date: 2025-07-03
    description: "The roof was put on today, marking a major milestone in the construction"
  
  - title: "Windows and Sliding Doors"
    date: 2025-07-22
    description: "Big sliding doors and windows were installed, bringing natural light into the house"
```

Each event automatically calculates the Monday date of its week for frontend navigation. Events are included in `metadata.json` with:
- `title`: Event name
- `date`: Event date (ISO format)
- `monday_date`: Monday of the event's week (YYMMDD format for video filename matching)
- `description`: Optional details

## Important Notes

1. **No test framework** - Project lacks unit/integration tests
2. **ESLint/TypeScript errors** ignored in frontend production builds
3. **Images unoptimized** in Next.js for Cloudflare Workers compatibility
4. **Incremental processing** - Only processes new days, maintains state
5. **Video compression** - Different settings for daily vs combined videos
6. **Frontend metadata** - Generated after each processing run, includes events
7. **Events system** - Edit events.yaml to add construction milestones for easy frontend navigation