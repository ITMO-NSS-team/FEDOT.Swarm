# syntax=docker/dockerfile:1.7
# One image for the demo: the Python engine and benchmarks under uv, marker with its weights
# and a llama.cpp server for OCR, OpenCode, and the built Fresh front end served by Deno.
# Everything is pinned; nothing is downloaded at run time.

ARG UV_VERSION=0.9.28
ARG UV_APP_VERSION=0.12.2
ARG DENO_VERSION=2.9.6
ARG OPENCODE_VERSION=1.18.20
ARG LLAMA_BUILD=b11036

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM ghcr.io/astral-sh/uv:${UV_APP_VERSION} AS uvapp
FROM denoland/deno:bin-${DENO_VERSION} AS denobin

# marker in its own tool environment (torch CPU), weights warmed into HF_HOME
FROM python:3.11-slim-trixie AS tools
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/opt/uv-tools/bin \
    HF_HOME=/opt/models/hf \
    HF_HUB_DISABLE_PROGRESS_BARS=1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv tool install marker-pdf==2.0.0 --python 3.11 \
      --index https://download.pytorch.org/whl/cpu
RUN /opt/uv-tools/marker-pdf/bin/python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('datalab-to/surya_layout2'); \
snapshot_download('datalab-to/surya-ocr-2-gguf')"
COPY benchmarks/paperbench/data/classifier-free-guidance/paper.pdf /tmp/warm.pdf
RUN /opt/uv-tools/bin/marker_single /tmp/warm.pdf --mode fast --output_format markdown \
      --output_dir /tmp/warm --disable_image_extraction --disable_multiprocessing \
      --disable_ocr --page_range 0 \
    && rm -rf /tmp/warm /tmp/warm.pdf

# the front end, built once
FROM denoland/deno:${DENO_VERSION} AS web
WORKDIR /app/web
COPY web/deno.json web/deno.lock ./
RUN deno install --frozen
COPY web ./
RUN rm -rf e2e && deno task build

FROM python:3.11-slim-trixie
ARG DENO_VERSION
ARG OPENCODE_VERSION
ARG LLAMA_BUILD
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends \
      git procps curl ca-certificates unzip libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uvapp /uv /usr/local/bin/uv
COPY --from=denobin /deno /usr/local/bin/deno
COPY --from=tools /opt/uv-tools /opt/uv-tools
COPY --from=tools /opt/models /opt/models

# llama.cpp server for marker's OCR
RUN set -eux; arch="$( [ "$TARGETARCH" = "arm64" ] && echo arm64 || echo x64 )"; \
    curl -fsSL -o /tmp/llama.tar.gz \
      "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_BUILD}/llama-${LLAMA_BUILD}-bin-ubuntu-${arch}.tar.gz"; \
    mkdir -p /opt/llama && tar -xzf /tmp/llama.tar.gz -C /opt/llama --strip-components=1; \
    rm /tmp/llama.tar.gz; \
    bin="$(find /opt/llama -name llama-server -type f | head -1)"; \
    ln -s "$bin" /usr/local/bin/llama-server; \
    echo "$(dirname "$bin")" > /etc/ld.so.conf.d/llama.conf && ldconfig; \
    llama-server --version

# OpenCode, pinned
RUN curl -fsSL https://opencode.ai/install | VERSION=${OPENCODE_VERSION} bash \
    && mv /root/.opencode/bin/opencode /usr/local/bin/opencode \
    && opencode --version

WORKDIR /app
ENV UV_FROZEN=1 \
    UV_NO_SYNC=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/opt/uv-tools/bin \
    HF_HOME=/opt/models/hf \
    HF_HUB_OFFLINE=1 \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    DENO_DIR=/deno-dir \
    PATH=/opt/uv-tools/bin:/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
RUN --mount=type=cache,target=/tmp/uv-cache \
    UV_NO_SYNC=0 uv sync --all-packages --extra pydantic-ai --extra opencode --group paperbench --frozen --no-dev
COPY benchmarks ./benchmarks
COPY docs ./docs
COPY --from=web /deno-dir /deno-dir
COPY --from=web /app/web ./web
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data && chown -R app:app /data /app /deno-dir \
    && chmod +x /usr/local/bin/entrypoint.sh
USER app
VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
