# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

```bash
# Start development server
pnpm dev

# Build the Next.js application
pnpm build

# Run linter
pnpm lint

# Start production server (after build)
pnpm start

# Build and preview with OpenNext for Cloudflare
pnpm preview

# Build and deploy to Cloudflare Workers
pnpm deploy

# Generate Cloudflare types
pnpm cf-typegen
```

## High-Level Architecture

This is a Next.js 15 application designed to display timelapse videos of the Northgrove house building project. The application is deployed to Cloudflare Workers using OpenNext.

### Key Components:

1. **Video Viewer (`app/page.tsx`)**: The main component that:
   - Fetches metadata from Cloudflare R2 storage
   - Displays timelapse videos in three modes: daily, weekly, or full project
   - Uses URL search params for navigation:
     - `/?view=day` - Today's timelapse
     - `/?view=week&date=YYYY-MM-DD` - Specific week (Monday date)
     - `/?view=full` - Full project timelapse
   - Allows users to navigate between different weeks
   - Handles video playback and error states

2. **Data Flow**:
   - Metadata is fetched from `https://nthgrv.mcgrath.nz/timelapse/metadata.json`
   - Videos are served from the same R2 bucket:
     - `day.mp4` - Today's timelapse
     - `week.mp4` - Current week's timelapse
     - `weeks/timelapse_week_YYYY-MM-DD.mp4` - Historical weekly videos
     - `full.mp4` - Complete project timelapse

3. **UI Components**: Uses shadcn/ui components (in `components/ui/`) built on Radix UI primitives with Tailwind CSS styling

4. **Deployment**:
   - Uses OpenNext.js adapter for Cloudflare Workers deployment
   - Configuration in `wrangler.jsonc` and `open-next.config.ts`
   - Build artifacts go to `.open-next/` directory

### Important Configuration Notes:

- ESLint and TypeScript errors are ignored during builds (see `next.config.mjs`)
- Images are served unoptimized for Cloudflare Workers compatibility
- The application uses pnpm as the package manager
