FROM ubuntu:rolling

ENV DEBIAN_FRONTEND=noninteractive

COPY . /usr/src/process-media

WORKDIR /usr/src/process-media

RUN apt-get update && apt-get install -y \
 perl \
 jpeginfo \
 libimage-exiftool-perl \
 libimage-magick-perl \
 libmime-types-perl \
 libsys-cpu-perl \
 libterm-readkey-perl \
 libyaml-tiny-perl

ENTRYPOINT ["/usr/src/process-media/process-media", "/media"]
