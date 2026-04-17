FROM python:3.12-slim

# Drop root for defence in depth — MCP server doesn't need elevated
# privileges, and containers often inherit pod-level securityContext that
# forbids root.
RUN useradd --create-home --shell /bin/bash mcp

RUN pip install --no-cache-dir allure-testops-mcp

USER mcp
WORKDIR /home/mcp

ENTRYPOINT ["allure-testops-mcp"]
