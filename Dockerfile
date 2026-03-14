FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required (sqlite3 is built-in to python usually, but keeping it light)
# RUN apt-get update && apt-get install -y --no-install-recommends ...

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything else
COPY . .

# Data directory will be volume mounted
RUN mkdir -p /app/data
