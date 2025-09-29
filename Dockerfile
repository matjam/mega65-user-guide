FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

# Install separate chunks of packages rather than doing it in one go because if you do that
# and then need to add another package its another rebuild of the entire layer. So, this
# is faster in development and marginally worse in CI.

# Base build tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git make build-essential pkg-config gcc g++ \
       libssl-dev libhpdf-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Graphics utilities (separate layer)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ghostscript inkscape imagemagick \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# TeX toolchain (large layer)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       latexmk texlive-full \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Pandoc (separate layer)
RUN apt-get update \
    && apt-get install -y --no-install-recommends pandoc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python + webfont tooling (system packages to avoid pip in system site)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-fonttools woff2 fontforge python3-fontforge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

# Usage (from repo root):
#   docker build -t mega65-docs .
#   docker run --rm -v "$PWD":/work -w /work mega65-docs make mega65-book.pdf
