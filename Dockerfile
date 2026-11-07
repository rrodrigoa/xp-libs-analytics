FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 POLARS_MAX_THREADS=2
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir --upgrade 'pip>=26.3' && python -m pip install --no-cache-dir -c requirements-lock.txt '.[mcp]' && useradd --uid 10001 --create-home analytics
USER 10001
ENTRYPOINT ["xp-libs-analytics"]
