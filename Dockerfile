# Use a slim Python base image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# Install uv, our package manager
RUN pip install uv

# Copy dependency definition files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --no-dev

# Copy the rest of the application code
COPY . .

# Set the entrypoint for the container
CMD ["uv", "run", "python", "worker.py"]
