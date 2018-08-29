FROM debian:stretch-slim

LABEL maintainer="Laurent Lavaud <l.lavaud@gmail.com>"

ENV DEBIAN_FRONTEND=noninteractive LANG=en_US.UTF-8 LC_ALL=C.UTF-8 LANGUAGE=en_US.UTF-8

COPY . /usr/src/process-media

COPY process-media.yaml /etc/process-media.yaml

WORKDIR /usr/src/process-media

RUN apt-get update && apt-get install -y --no-install-recommends \
 perl \
 jpeginfo \
 libimage-exiftool-perl \
 libimage-magick-perl \
 libmime-types-perl \
 libsys-cpu-perl \
 libterm-readkey-perl \
 libyaml-tiny-perl \
&& rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["/usr/src/process-media/process-media", "--config", "/etc/process-media.yaml", "/media"]
