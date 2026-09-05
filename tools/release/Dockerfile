FROM python:3.14.7-slim-bookworm@sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9

ENV TZ=UTC \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONHASHSEED=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_INPUT=1 \
    PIP_CONFIG_FILE=/dev/null \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_EXTRA_INDEX_URL="" \
    PIP_FIND_LINKS="" \
    PIP_NO_CACHE_DIR=1

COPY requirements/release.txt /opt/threadroot/release-requirements.txt

RUN python -m pip install --no-cache-dir --no-deps --require-hashes --only-binary=:all: \
      -r /opt/threadroot/release-requirements.txt \
    && python -m pip check

WORKDIR /workspace
