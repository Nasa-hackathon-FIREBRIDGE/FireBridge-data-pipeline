FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements-data.lock ./
RUN pip install --no-cache-dir -r requirements-data.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
ENV PYTHONUNBUFFERED=1
CMD ["firebridge", "worker"]
