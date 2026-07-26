# syntax=docker/dockerfile:1
# ============================================================
# EllenSings gateway: tun2socks + iptables kill-switch
#
# tun2socks собирается из исходников на закреплённой версии
# с проверкой SHA256 — готовые бинарники в репозитории не хранятся.
# ============================================================

FROM golang:1.26-alpine AS build

SHELL ["/bin/ash", "-eo", "pipefail", "-c"]

# Закреплённая версия tun2socks и SHA256 архива исходников.
# При обновлении версии пересчитай хеш:
#   curl -fsSL -o src.tar.gz https://github.com/xjasonlyu/tun2socks/archive/refs/tags/v<VER>.tar.gz
#   sha256sum src.tar.gz
ARG TUN2SOCKS_VERSION=2.7.0
ARG TUN2SOCKS_SHA256=7f54d5ccc38f0cfe3ec91b4b1c5e5a50e0f5de96982eb60288d3f8c54d9030ab

WORKDIR /src

ADD https://github.com/xjasonlyu/tun2socks/archive/refs/tags/v${TUN2SOCKS_VERSION}.tar.gz /tmp/tun2socks-src.tar.gz

RUN echo "${TUN2SOCKS_SHA256}  /tmp/tun2socks-src.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/tun2socks-src.tar.gz --strip-components=1 \
    && rm /tmp/tun2socks-src.tar.gz \
    && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/tun2socks .

# ---------- runtime ----------
FROM alpine:3.22

# iproute2  — ip tuntap / ip route
# iptables  — kill-switch (включает ip6tables)
# musl-utils — getent для резолва хоста прокси
# curl + ca-certificates — healthcheck через туннель
# hadolint ignore=DL3018
RUN apk add --no-cache \
    iproute2 \
    iptables \
    musl-utils \
    unbound \
    curl \
    ca-certificates

COPY --from=build /out/tun2socks /usr/local/bin/tun2socks
COPY entrypoint.sh healthcheck.sh /usr/local/bin/
COPY unbound.conf /etc/unbound/ellensings.conf
RUN chmod 755 /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh

# Проверяем не «жив ли процесс», а фактическую работоспособность маршрута
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
