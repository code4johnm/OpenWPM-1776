FROM ubuntu:22.04

SHELL ["/bin/bash", "-c"]

# Update ubuntu and setup conda
# adapted from: https://hub.docker.com/r/conda/miniconda3/dockerfile
RUN sed -i'' 's/archive\.ubuntu\.com/us\.archive\.ubuntu\.com/' /etc/apt/sources.list
RUN apt-get clean -qq \
    && rm -r /var/lib/apt/lists/* -vf \
    && apt-get clean -qq \
    && apt-get update -qq \
    && apt-get upgrade -qq \
    # git and make, wget for `install-conda`
    && apt-get install wget git make -qq \
    # Chromium + xvfb runtime deps
    && apt-get install -qq xvfb libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
       libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
       libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libgtk-3-0 fonts-liberation

ENV HOME /opt
COPY scripts/install-conda.sh .
RUN ./install-conda.sh
ENV PATH $HOME/conda/bin:$PATH

# Install OpenWPM. Playwright browsers live outside a bind-mounted source tree.
ENV PLAYWRIGHT_BROWSERS_PATH /opt/ms-playwright
WORKDIR /opt/OpenWPM
COPY . .
RUN ./install.sh
ENV PATH $HOME/conda/envs/openwpm/bin:$PATH
ENV OPENWPM_NO_SANDBOX 1
ENV OPENWPM_DISABLE_DEV_SHM 1

# Setting demo.py as the default command
CMD [ "python", "demo.py"]
