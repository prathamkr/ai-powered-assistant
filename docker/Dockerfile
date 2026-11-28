# Reproducible build environment for the Lazey APK (buildozer + python-for-android).
#
# Always linux/amd64: the Android NDK ships x86_64 Linux tools only. On Apple Silicon this image runs
# through Rosetta (Lima / OrbStack / Docker Desktop with Rosetta on); on Intel/AMD Linux and GitHub
# Actions it runs natively. Use docker/build.sh rather than calling this directly.
#
# Pinned here: Ubuntu 24.04, OpenJDK 17, buildozer and its Python helpers (versions from the first
# build that worked on the phone, 2026-11-26). Pinned in buildozer.spec: python-for-android branch
# (which pins NDK r28c), Android API 34. SDK/NDK downloads are cached in a volume, not in the image.
FROM --platform=linux/amd64 ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-dev python3-pip git zip unzip rsync patch ca-certificates curl \
        openjdk-17-jdk-headless build-essential autoconf automake libtool pkg-config cmake ccache lld \
        libffi-dev libssl-dev zlib1g-dev libltdl-dev \
    && rm -rf /var/lib/apt/lists/*

# buildozer runs `pip install --user <python-for-android helpers>`, which a plain venv refuses
# ("User site-packages are not visible in this virtualenv"): hence --system-site-packages. The
# helpers are installed into the venv up front at fixed versions, so that later --user call finds
# them all satisfied and installs nothing.
RUN python3 -m venv --system-site-packages /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir buildozer==1.6.0 Cython==0.29.37 setuptools==68.1.2 \
        appdirs==1.4.4 colorama==0.4.6 Jinja2==3.1.2 sh==2.4.0 meson==1.12.1 ninja==1.13.2 build==1.6.1 \
        toml==0.10.2 packaging==24.0 wheel==0.43.0

ENV PATH=/opt/venv/bin:/root/.local/bin:$PATH

COPY build-apk.sh /usr/local/bin/build-apk
RUN chmod +x /usr/local/bin/build-apk && mkdir -p /src /out /work/.buildozer /root/.buildozer

ENTRYPOINT ["build-apk"]
