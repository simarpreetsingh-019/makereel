# makereel for any Linux server, NAS or cloud VM.
#   docker build -t makereel .
#   docker run -d --restart unless-stopped -p 8765:8765 \
#     -e MAKEREEL_WEB_PASSWORD=change-me -v "$PWD/data:/data" makereel
FROM python:3.12-slim

# Debian's ffmpeg includes libass (text captions); nodejs lets yt-dlp pass YouTube's player checks
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg nodejs fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# all user data (settings, reels, downloads) lives in the /data volume
WORKDIR /data
ENV MAKEREEL_HOST=0.0.0.0 \
    MAKEREEL_THREADS=2 \
    PYTHONUNBUFFERED=1
EXPOSE 8765
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health')" || exit 1
CMD ["makereel", "web", "--no-browser"]
