FROM ubuntu:rolling

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
 software-properties-common \
 wget \
 gpg

RUN ["/bin/bash", "-c", "set -o pipefail && wget -O - https://llavaud.github.io/process-media/apt/conf/gpg.key | apt-key add -"]
RUN apt-add-repository 'deb https://llavaud.github.io/process-media/apt stable main'
RUN apt-get install -y process-media

ENTRYPOINT ["/usr/bin/process-media", "/media"]
