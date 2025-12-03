# ===========================
#   Python 3.10 + Torch CPU
#   Railway-compatible image
# ===========================

FROM python:3.10-slim

# Clean & system deps
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libsm6 libxext6 libxrender1 libgl1 \
    && apt-get clean

WORKDIR /app
COPY . /app

# Install pip + torch CPU + ultralytics
RUN pip install --upgrade pip
RUN pip install torch==2.2.2 torchvision==0.17.2 torchaudio==2.2.2 --index-url https://download.pytorch.org/whl/cpu
RUN pip install -r requirements.txt

EXPOSE 5000

# Create necessary directories
RUN mkdir -p images models templates static

CMD ["python", "app.py"]