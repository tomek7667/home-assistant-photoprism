# Similar-photo search for PhotoPrism Library (CPU; arm64 and amd64)
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY ppl_similarity.py /app/ppl_similarity.py

# The model is downloaded once into the data volume
ENV HF_HOME=/data/huggingface \
    PYTHONUNBUFFERED=1
WORKDIR /app
EXPOSE 8765
CMD ["python", "ppl_similarity.py", "serve"]
