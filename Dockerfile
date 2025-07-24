# Use a slim Python base image
FROM python:3.13-slim

# Set the working directory
WORKDIR /app

# Install ffmpeg
RUN apt-get update && apt-get install --no-install-recommends -y ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install uv, our package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --no-dev

# Copy the rest of the application code
COPY . .

# Set the entrypoint for the container
CMD ["uv", "run", "--no-dev", "python", "worker.py"]
