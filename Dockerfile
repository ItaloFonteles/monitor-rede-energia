FROM python:3.12-slim

# ping para as verificações de rede
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /monitor
COPY app ./app
COPY simulador ./simulador

ENV PYTHONUNBUFFERED=1 TZ=America/Boa_Vista
EXPOSE 8090
CMD ["python", "-m", "app.main"]
