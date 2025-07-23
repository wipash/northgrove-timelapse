# Timelapse Automation Plan

This document outlines the necessary changes to run the timelapse generation script in an automated, serverless environment.

### **High-Level Goal**

Automate the generation of daily and weekly timelapse videos by running the Python script in a serverless environment like Google Cloud Run, triggered on a schedule. The full, all-time timelapse will remain a manual process.

### **Key Challenges & Solutions**

1.  **Filesystem Access:** The script reads from a local Google Drive folder. This is not possible in a serverless environment.
    *   **Solution:** Use the **Google Drive API** to list and download image files. This will require setting up a Google Cloud service account for authentication.

2.  **`ffmpeg` Dependency:** The script requires the `ffmpeg` command-line tool, which is not available in standard serverless function environments.
    *   **Solution:** Package the application in a **Docker container** with `ffmpeg` installed. This container can be deployed to a platform like **Google Cloud Run** or **AWS Lambda (with container support)**.

3.  **State Management:** The script uses a local `state.json` file and a local cache of daily videos. This state will be lost between runs in a stateless environment.
    *   **Solution:** Use the **Cloudflare R2 bucket** to store both the state file and the cached daily videos. The script will download the state/cache at the start of an execution and upload the updated versions at the end.

4.  **Configuration & Secrets:** Hardcoding credentials and configuration in `config.yaml` is not secure or flexible for a cloud environment.
    *   **Solution:** Adapt the script to read all configuration and secrets from **environment variables**. This is a standard practice for cloud-native applications.

### **Detailed Plan of Action**

**Phase 1: Code Refactoring**

1.  **Google Drive API Integration:**
    *   [ ] Add `google-api-python-client` and `google-auth-httplib2` to the project dependencies.
    *   [ ] Create a new module (e.g., `gdrive.py`) to encapsulate all Google Drive API interactions.
    *   [ ] Implement a function to authenticate using a service account JSON key (loaded from an environment variable).
    *   [ ] Rewrite `get_daily_folders` to use the API to list folders from the specified Google Drive parent folder.
    *   [ ] Rewrite `get_images_from_folder` to list and download images from a Drive folder into a temporary directory.

2.  **R2-based State and Cache:**
    *   [ ] Modify `load_state` to first attempt to download `state.json` from R2 (e.g., from `state/state.json`).
    *   [ ] Modify `save_state` to upload the `state.json` back to R2.
    *   [ ] In `create_daily_video`, check if the output video already exists in an R2 cache prefix (e.g., `cache/daily/`). If so, download it instead of recreating.
    *   [ ] After creating a daily video, upload it to the R2 cache prefix.
    *   [ ] The `create_combined_video` function will need to download its input videos from the R2 cache.

3.  **Configuration via Environment Variables:**
    *   [ ] Remove the dependency on `config.yaml`.
    *   [ ] In `TimelapseProcessor.__init__`, read all configuration values (R2 settings, source paths, video settings) from environment variables.
    *   [ ] Document the required environment variables in the `README.md`.

4.  **Create an Automated Entry Point:**
    *   [ ] Create a new function or script (e.g., `worker.py`) that serves as the entry point for the serverless function.
    *   [ ] This entry point will call the main `process` function with fixed arguments suitable for automated runs (e.g., `build_full=False`, `upload_all_weeks=False`).

**Phase 2: Containerization & Deployment**

1.  **Create `Dockerfile`:**
    *   [ ] Start from a `python:3.11-slim` base image.
    *   [ ] Use `apt-get` to install `ffmpeg`.
    *   [ ] Install Python dependencies using `uv`.
    *   [ ] Copy the application source code.
    *   [ ] Set the `CMD` to run the automated entry point script (`worker.py`).

2.  **Google Cloud Setup:**
    *   [ ] Create a new Google Cloud Project.
    *   [ ] Enable the Google Drive API.
    *   [ ] Create a Service Account, grant it access to the Drive folder, and download its JSON key.
    *   [ ] Create a Google Artifact Registry to store the Docker image.

3.  **Deployment to Google Cloud Run:**
    *   [ ] Build the Docker image and push it to the Artifact Registry.
    *   [ ] Create a new Cloud Run service using the deployed image.
    *   [ ] Configure the service with all required environment variables:
        *   R2 credentials (`R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, etc.)
        *   Google Drive Folder ID (`GDRIVE_FOLDER_ID`)
        *   The content of the Google Service Account JSON key (`GDRIVE_SA_KEY`).
    *   [ ] Set up **Cloud Scheduler** to trigger the Cloud Run service URL on a recurring basis (e.g., every 3 hours).

### **Manual Process for Full Timelapse**

The `--build-full` flag will still be available for local execution. To generate a new full timelapse, a user will:
1.  Ensure their local `config.yaml` is correct.
2.  Run the script locally with the `--build-full` flag: `uv run python timelapse.py --build-full`.
3.  This will use the latest daily videos (cached in R2) to build the full video and upload it.
