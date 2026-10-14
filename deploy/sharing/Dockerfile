FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[api]' && useradd --uid 10001 --create-home vault && mkdir /data && chown vault:vault /data
USER 10001:10001
EXPOSE 8788
CMD ["vault-share", "--host", "0.0.0.0", "--database", "/data/sharing.db", "--admin-token-file", "/run/secrets/sharing_admin"]
