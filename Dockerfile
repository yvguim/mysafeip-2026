FROM docker.io/library/python:3.12-slim

COPY requirements.txt /tmp/requirements.txt

# Skip bytecode compilation during the emulated ARM64 build.
RUN python -m pip install --no-cache-dir --no-compile -r /tmp/requirements.txt

WORKDIR /app/
COPY build/start.sh /start.sh
RUN chmod +x /start.sh

COPY app /app
COPY scripts/reset_admin.py /app/scripts/reset_admin.py

RUN groupadd --gid 10001 mysafeip \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin mysafeip \
    && install -d -o 10001 -g 10001 -m 0750 /data

ENV PYTHONPATH=/app
USER 10001:10001
EXPOSE 8000
CMD ["/start.sh"]
