ARG BASE_IMAGE=ubuntu:24.04
FROM $BASE_IMAGE

LABEL maintainer=“neotech”
ENV LANG C.UTF-8
ENV TZ Asia/Shanghai

RUN apt-get update
RUN apt-get update && apt-get install -y \
    git \
    tcsh \
    vim \
    curl \
    python3 \
    python3-pip \
    libgirepository-1.0-1 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    fonts-wqy-zenhei \
    fonts-noto-cjk
    
RUN mv /usr/lib/python3.12/EXTERNALLY-MANAGED /usr/lib/python3.12/EXTERNALLY-MANAGED.bak
ADD ./requirements.txt /opt/workspace/neotech/requirements.txt
WORKDIR /opt/workspace/neotech
RUN pip install -r requirements.txt

ADD ./mRNAPredictionAgent /opt/workspace/neotech/mRNAPredictionAgent
WORKDIR /opt/workspace/neotech/mRNAPredictionAgent

EXPOSE 60718

CMD ["sh","./run.sh"]
