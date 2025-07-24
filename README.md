# Northgrove Timelapse Tool

Processes construction camera images from Google Drive and creates timelapse videos, uploading them to Cloudflare R2.

This project is designed to be run in two ways:
1.  **Automated Serverless Worker**: Runs on a schedule (e.g., every few hours) to process recent images into daily and weekly videos.
2.  **Manual Local Execution**: Run on a local machine to perform larger tasks, like generating the full end-to-end timelapse.

## Automated Processing (Serverless)

The system is designed to be deployed as a containerized application to a serverless platform like Google Cloud Run or AWS Fargate.

### What it Does (Automated)

- Scans a specified Google Drive folder for daily image folders.
- Creates videos for the last 3 days (to catch up on any late uploads).
- Creates an updated video for the current week (Monday to today).
- Uploads the daily, weekly, and latest image to Cloudflare R2.
- Updates a `metadata.json` file in R2 for use by a web frontend.

### Running with Docker

A `Dockerfile` is provided to build a container image with all necessary dependencies (`python`, `ffmpeg`, `uv`).

**1. Build the Docker image:**

```bash
docker build -t timelapse-worker .
```

**2. Run the container with environment variables:**

To run the container, you must provide the necessary configuration as environment variables. Create a `.env` file:

```
# .env file
GDRIVE_FOLDER_ID="your_google_drive_folder_id"
# For GDRIVE_SA_KEY, you can use either:
# Option 1: Base64-encoded (recommended for deployment)
# GDRIVE_SA_KEY="base64_encoded_json_here"
# To encode: base64 -w0 < your-service-account-key.json
# Option 2: Plain JSON (be careful with quotes)
# GDRIVE_SA_KEY='{"type": "service_account", "project_id": "...", ...}'
GDRIVE_SA_KEY="your_base64_encoded_or_plain_json_key"
R2_ENDPOINT_URL="https://<account-id>.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID="your_r2_access_key"
R2_SECRET_ACCESS_KEY="your_r2_secret"
R2_BUCKET_NAME="your_r2_bucket_name"
FOLDER_PATTERN_PREFIX="TLST04A00879_"
```

Then run the container:

```bash
docker run --rm --env-file .env timelapse-worker
```

The container will execute the `worker.py` script, which processes the last few days and then exits.

### Deployment to Google Cloud Run

1.  **Enable APIs & Create Service Account:**
    *   In your Google Cloud project, enable the **Google Drive API** and **Artifact Registry API**.
    *   Create a **Service Account**. Grant it "Viewer" access to the Google Drive folder containing the images.
    *   Download the JSON key for the service account. The contents of this file will be your `GDRIVE_SA_KEY`.

2.  **Build and Push the Docker Image:**
    *   Configure Docker to authenticate with Google Artifact Registry.
    *   Build and tag the image: `docker build -t us-central1-docker.pkg.dev/YOUR_PROJECT/timelapse/worker:latest .`
    *   Push the image: `docker push us-central1-docker.pkg.dev/YOUR_PROJECT/timelapse/worker:latest`

3.  **Deploy the Cloud Run Service:**
    *   Create a new Cloud Run service, selecting the container image you just pushed.
    *   In the "Variables & Secrets" section, add all the environment variables from the `.env` file. For `GDRIVE_SA_KEY`, it's recommended to use Google Secret Manager.
    *   Configure the service with sufficient memory (e.g., 2-4 GiB) and CPU.
    *   Set the execution timeout to a reasonable value (e.g., 15-30 minutes).

4.  **Schedule the Service:**
    *   Use **Cloud Scheduler** to create a new job.
    *   Set the target to "HTTP" and the URL to the URL of your Cloud Run service.
    *   Set the schedule (e.g., `0 */3 * * *` to run every 3 hours).

## Manual Local Execution

For tasks like building the full timelapse, you can run the script locally.

### Setup

1.  **Install Dependencies:**
    ```bash
    uv sync
    ```

2.  **Configure Google Drive Authentication:**
    
    For local development, you have two options:
    
    **Option A: Use auth.json file (Recommended for local development)**
    - Place your Google service account JSON key in a file named `auth.json` in the project root
    - The script will automatically detect and use this file
    
    **Option B: Use environment variable**
    - Set the `GDRIVE_SA_KEY` environment variable with either:
      - Plain JSON: `export GDRIVE_SA_KEY='{"type": "service_account", ...}'`
      - Base64-encoded JSON: `export GDRIVE_SA_KEY=$(base64 < your-key.json)`

3.  **Set Other Environment Variables:**
    Export the required environment variables in your shell:
    ```bash
    export GDRIVE_FOLDER_ID="your_google_drive_folder_id"
    export R2_ENDPOINT_URL="https://<account-id>.r2.cloudflarestorage.com"
    export R2_ACCESS_KEY_ID="your_r2_access_key"
    export R2_SECRET_ACCESS_KEY="your_r2_secret"
    export R2_BUCKET_NAME="your_r2_bucket_name"
    ```

### Usage

The `timelapse.py` script provides command-line arguments for more control.

```bash
# Show help
uv run python timelapse.py --help

# Build the FULL timelapse video (can be slow)
uv run python timelapse.py --build-full

# Process only the last 10 days
uv run python timelapse.py --days 10

# Upload all historical week videos (useful for initial setup)
uv run python timelapse.py --upload-all-weeks
```

## State Management

The script tracks processed folders and other metadata in a `state.json` file, which is stored in the R2 bucket at `state/state.json`. This allows the process to be stateless and resume correctly on each run.
