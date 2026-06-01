# Builder stage — build the Python wheel
FROM quay.io/fedora/python-314-minimal AS builder

RUN pip install --no-cache-dir uv

WORKDIR /tmp/src
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
RUN uv build

# Builder stage — build DepotDownloader
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS dd-builder
COPY vendor/DepotDownloader /src
RUN dotnet publish /src/DepotDownloader/ \
    -c Release -r linux-x64 \
    --self-contained true \
    -p:PublishSingleFile=true \
    -p:PublishTrimmed=false \
    -p:AssemblyName=DepotDownloader \
    -p:InvariantGlobalization=true \
    -o /out

# Final stage — runtime environment
FROM quay.io/fedora/fedora-minimal:44 AS runtime

LABEL org.opencontainers.image.title="Enshrouded Dedicated Server"
LABEL org.opencontainers.image.description="Enshrouded Dedicated Server Container"
LABEL org.opencontainers.image.licenses="BlueOak-1.0.0"
LABEL org.opencontainers.image.vendor="Lincoln Nogueira"
LABEL org.opencontainers.image.source="https://github.com/lincolnthalles/enshrouded-container"

ENV HOME=/home/steam
ENV PUID=1000
ENV PGID=1000
ENV XDG_RUNTIME_DIR=/var/run/user/${PUID}
ENV WINEPREFIX=/data/wineprefix

RUN rm -f /etc/yum.repos.d/fedora-cisco-openh264.repo
RUN dnf5 install -y --allowerasing --setopt=install_weak_deps=False \
        python3 \
        python3-pip \
        procps-ng \
        util-linux \
        xorg-x11-server-Xvfb \
        wine-core \
        wine-common \
        wine-ldap

RUN mkdir -p /opt/depotdownloader
COPY --from=dd-builder /out/DepotDownloader /opt/depotdownloader/DepotDownloader

RUN groupadd -g ${PGID} steam && \
    useradd -u ${PUID} -g ${PGID} -d /home/steam -m -s /bin/bash steam && \
    mkdir -p \
        /data/backups \
        /data/config \
        /data/logs \
        /data/manifests \
        /data/mods \
        /data/saves \
        /data/wineprefix && \
    chown -R steam:steam /home/steam /data

RUN cat /proc/sys/kernel/random/uuid > /etc/machine-id

# Copy and install the built wheel
COPY --from=builder /tmp/src/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl

# Remove any leftover files from the builder stage
RUN rm -rf /tmp/* /var/tmp/* && \
    dnf5 remove -y python3-pip && \
    dnf5 autoremove -y && \
    dnf5 clean all

WORKDIR /data/gameserver
ENTRYPOINT ["enshctl"]
CMD ["start"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD pgrep -f enshrouded_server.exe > /dev/null || exit 1
