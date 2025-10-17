FROM flink:1.19.2-scala_2.12-java8

RUN set -ex; \
  apt-get update && \
  apt-get install -y python3 python3-pip openjdk-8-jdk && \
  ln -s /usr/bin/python3 /usr/local/bin/python && \
  apt-get clean

COPY build/jars/flink-sql-connector-kafka-3.2.0-1.18.jar /opt/flink/lib/
COPY build/jars/flink-connector-jdbc-3.1.1-1.17.jar /opt/flink/lib/
COPY build/jars/postgresql-42.7.0.jar /opt/flink/lib/

WORKDIR /opt/flink/app

COPY build/app/requirements.txt .
RUN pip install -r requirements.txt

COPY build/app/jobs ./jobs