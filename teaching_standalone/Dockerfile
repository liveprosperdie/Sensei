# Study Room - Standalone Adaptive AI Tutor Web App
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Environment defaults for cloud web hosting
ENV PORT=8080
ENV HOST=0.0.0.0
ENV HEADLESS=true
ENV AKIRA_TEACHING_DIR=/app/data

# Persistent workspace data directory
VOLUME ["/app/data"]

EXPOSE 8080

CMD ["python", "-m", "teaching", "--host", "0.0.0.0", "--port", "8080", "--no-browser"]
