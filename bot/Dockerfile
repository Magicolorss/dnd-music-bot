FROM python:3.11-slim
RUN pip install requests yt-dlp
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY dnd_bot.py .
CMD ["python3", "dnd_bot.py"]