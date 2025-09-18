FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    nginx \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

COPY nginx.conf /etc/nginx/sites-enabled/default

RUN mkdir -p /var/run/nginx

EXPOSE 80

CMD ["sh", "-c", "service nginx start && gunicorn openpilot_viewer.wsgi:application --bind 0.0.0.0:8000"]
