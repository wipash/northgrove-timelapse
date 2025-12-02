# Use a slim Python base image
FROM python:3.13-slim

# Set the working directory
WORKDIR /app

# Install ffmpeg (static build is way smaller than installing from apt)
COPY --from=mwader/static-ffmpeg:7.1.1@sha256:11a44711684c0b9f754c047dcd64235b8b52deab251bd0e0a86f22faa160749c /ffmpeg /usr/local/bin/

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.8.3@sha256:ef11ed817e6a5385c02cd49fdcc99c23d02426088252a8eace6b6e6a2a511f36 /uv /uvx /bin/

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --no-dev

# Copy the rest of the application code
COPY . .

# Set the entrypoint for the container
# Args: (none) = daily processing, "full" = build full timelapse from weekly videos
ENTRYPOINT ["uv", "run", "--no-dev", "python", "-u", "worker.py"]
