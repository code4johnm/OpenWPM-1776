# OpenWPM-1776 OCI image: Playwright + pinned Chromium measurement runtime.
# Compatible with Docker Buildx, Podman, and Buildah (`podman build -f Dockerfile .`).
# Chromium in this image always uses --no-sandbox (container + OPENWPM_NO_SANDBOX).
# Do not treat this as a general-purpose browser. Outputs are sensitive research data.

FROM ubuntu:22.04

LABEL org.opencontainers.image.title="OpenWPM-1776" \
      org.opencontainers.image.description="Playwright Chromium web privacy measurement platform" \
      org.opencontainers.image.source="https://github.com/code4johnm/OpenWPM-1776" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="0.35.0"

SHELL ["/bin/bash", "-c"]

# tini: zombie reaping when the runtime does not pass --init (Compose sets init: true too).
RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
       ca-certificates \
       wget \
       git \
       make \
       tini \
       xvfb \
       fonts-liberation \
       libnss3 \
       libnspr4 \
       libatk1.0-0 \
       libatk-bridge2.0-0 \
       libcups2 \
       libdrm2 \
       libxkbcommon0 \
       libxcomposite1 \
       libxdamage1 \
       libxfixes3 \
       libxrandr2 \
       libgbm1 \
       libasound2 \
       libpango-1.0-0 \
       libcairo2 \
       libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

ENV HOME=/opt
COPY scripts/install-conda.sh /tmp/install-conda.sh
RUN bash /tmp/install-conda.sh && rm /tmp/install-conda.sh
ENV PATH=/opt/conda/bin:$PATH

# Playwright browsers stay outside WORKDIR so a source bind-mount cannot hide them.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
WORKDIR /opt/OpenWPM

# Layer cache: env pin + installer before the rest of the tree.
COPY environment.yaml install.sh ./
COPY scripts/ ./scripts/
COPY openwpm/ ./openwpm/
COPY VERSION ./
RUN chmod +x ./install.sh ./scripts/install-chromium.sh \
    && ./install.sh

COPY . .
RUN chmod +x /opt/OpenWPM/scripts/docker-entrypoint.sh \
    /opt/OpenWPM/scripts/install-chromium.sh
ENV PATH=/opt/conda/envs/openwpm/bin:$PATH

# Container Chromium cannot use the user-namespace sandbox. Residual risk: renderer
# escape is easier than on a sandboxed desktop. Dedicated measurement hosts only.
ENV OPENWPM_NO_SANDBOX=1 \
    OPENWPM_DISABLE_DEV_SHM=1 \
    OPENWPM_DATADIR=/opt/OpenWPM/datadir \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 --shell /bin/bash --user-group openwpm \
    && mkdir -p /opt/OpenWPM/datadir /opt/ms-playwright \
    && chown -R openwpm:openwpm /opt/OpenWPM /opt/ms-playwright /opt/conda /home/openwpm

USER 10001:10001
ENV HOME=/home/openwpm

VOLUME ["/opt/OpenWPM/datadir"]

# tini + entrypoint: mkdir/writable datadir, then exec the command (exit code preserved).
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/opt/OpenWPM/scripts/docker-entrypoint.sh"]
# Headless smoke is the image default. Override for demo/crawl (see compose.yaml).
CMD ["python", "-m", "openwpm.smoke", "--outdir", "/opt/OpenWPM/datadir"]
