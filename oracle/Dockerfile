# The oracle image. Build it once per lockfile change and record the digest in the
# plugin's oracle_image setting. The container runs with --network none, so every
# dependency the tests need is installed here.
#
# Replace the digest below with the one for the base image you build from:
#   docker pull python:3.12-slim && docker inspect --format '{{index .RepoDigests 0}}' python:3.12-slim
FROM python:3.12-slim@sha256:REPLACE_WITH_PINNED_DIGEST

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# The repository's dependencies, from its lockfile. Edit for the project under test.
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock

COPY grade.sh filter_diff.py /oracle/
RUN chmod +x /oracle/grade.sh

ENV TZ=UTC LC_ALL=C.UTF-8 PYTHONHASHSEED=0 SOURCE_DATE_EPOCH=1700000000
WORKDIR /work
