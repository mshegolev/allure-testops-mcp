FROM python:3.12-slim

RUN pip install --no-cache-dir allure-testops-mcp

ENTRYPOINT ["allure-testops-mcp"]
