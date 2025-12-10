FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (including build tools for bcrypt)
RUN apt-get update && apt-get install -y \
    libmagic1 \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Railway uses PORT env variable)
EXPOSE 8000

# Run the application using shell form to expand $PORT
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
