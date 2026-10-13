# Finance OTS Agent Task - Python environment with data analysis tools

FROM alpine/git:2.45.2 AS skills

ARG ANTHROPIC_SKILLS_REF=da20c92503b2e8ff1cf28ca81a0df4673debdbf7

RUN git clone --filter=blob:none --no-checkout https://github.com/anthropics/skills.git /tmp/anthropic-skills \
    && cd /tmp/anthropic-skills \
    && git sparse-checkout init --cone \
    && git sparse-checkout set skills/xlsx skills/pdf skills/docx \
    && git -c advice.detachedHead=false checkout "${ANTHROPIC_SKILLS_REF}" \
    && mkdir -p /harbor/skills \
    && cp -a skills/xlsx /harbor/skills/xlsx \
    && cp -a skills/pdf /harbor/skills/pdf \
    && cp -a skills/docx /harbor/skills/docx

FROM python:3.11-slim

WORKDIR /workspace

# System dependencies used by the document skills
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Agent-neutral Harbor skills directory
COPY --from=skills /harbor/skills /harbor/skills
RUN chmod -R a+rX /harbor/skills

# Install task dependencies
RUN pip install --no-cache-dir \
    numpy==2.3.3 \
    pandas==2.3.3 \
    matplotlib==3.10.7 \
    pypdf==6.7.0 \
    openpyxl \
    pdfplumber \
    pdf2image \
    pillow \
    defusedxml \
    lxml \
    python-docx \
    pytest \
    pyyaml

# Copy task data
COPY data/ /workspace/data/
