FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Create working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies using uv for extremely fast resolution
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip uv && uv pip install --system -r requirements.txt

# Copy the rest of the application code
COPY . /app/

# Expose port 8000 for FastAPI
EXPOSE 8000

# Run the uvicorn server
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
