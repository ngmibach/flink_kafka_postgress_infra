FROM flink:1.19.2-scala_2.12-java8

RUN set -ex; \
  apt-get update && \
  apt-get install -y build-essential python3-dev python3 python3-pip openjdk-8-jdk && \
  ln -s /usr/bin/python3 /usr/local/bin/python && \
  apt-get clean && rm -rf /var/lib/apt/lists/*

COPY build/jars/flink-sql-connector-kafka-3.2.0-1.18.jar /opt/flink/lib/
COPY build/jars/flink-connector-jdbc-3.1.1-1.17.jar /opt/flink/lib/
COPY build/jars/postgresql-42.7.0.jar /opt/flink/lib/

COPY build/app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /opt/flink/app/jobs/
COPY build/app/jobs/flink_job.py /opt/flink/app/jobs/