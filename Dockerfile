FROM python:3.12-slim
WORKDIR /app
COPY backend/ .
COPY tests/ ./tests/
RUN pip install pytest
CMD ["python", "-m", "pytest", "tests", "-v"]