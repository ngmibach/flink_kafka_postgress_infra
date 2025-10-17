Disclamer, this entire repos include ArgoCD, k9s, local registry, Kafka and PostgresDB, so if you have those system online, pls turn off.
I. Setup up k8s and argocd
start up:
after docker compose up -d completed go to argocd_central run
bash init.sh (build custom image and init git repo)

get argocd password:
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d

argocd https://localhost:30001
kubeopsview http://localhost:30002
appexample: http://localhost:30000

rebuild appexample to have different build by timestamp
go to folder app-example
bash build-image.sh

OR just run full_up.sh (^.^)

II. Setup up flink-kubernetes-operator
Since this setup require image from Bosch, you have to docker login into radium-pt-ac-smartqm-docker-release-local.rb-artifactory.bosch.com and pull down these two images:
+ radium-pt-ac-smartqm-docker-release-local.rb-artifactory.bosch.com/flink/flink-deployments:flink-kubernetes-operator
+ radium-pt-ac-smartqm-docker-release-local.rb-artifactory.bosch.com/flink/flink-deployments:flink-main-container-v119-aws
After that, move into flink_postgres_kafka_infra/argocd_central/docker_build and execute
+ docker compose build
+ docker compose push 
(If you don't want to run job and just want to run the kubernetes setup, command out these line in docker-compose.yaml
  flink-deploy-custom:
    image: localhost:5000/flink/flink-deployments:flink-main-container-custom
    build:
      context: build/flink_deploy_custom
      dockerfile: Dockerfile

  flink-deploy-producer:
    image: localhost:5000/flink/flink-deployments:flink-main-container-producer
    build: 
      context: build/flink_deploy_custom
      dockerfile: Dockerfile.producer
    environment:
      - PYTHONUNBUFFERED=1
)
After building and pushing the docker image, you have to run this command for the flink-kubernetes-operator to be installed:
+ kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.19.1/cert-manager.yaml
If after the above command, your flink-kubernetes-operator still doesn't managed to be installed, run this following command to manually install flink-kubernetes-operator:
+ helm repo add flink-operator-repo https://downloads.apache.org/flink/flink-kubernetes-operator-1.13.0/
+ helm repo update
+ helm install flink-kubernetes-operator flink-operator-repo/flink-kubernetes-operator -n workspace

III. Setup Kafka Source and PostgresDB Sink
Move into the /flink_postgres_kafka_infra/kafka and execute docker compose up -d 
After all containers are up, attach a shell to the Postgres container and execute the following line to construct table
+ psql -U test -d smart_monitoring_db
+ 
-- Create schema
CREATE SCHEMA sm_00002_vku_sinter;
GRANT USAGE ON SCHEMA sm_00002_vku_sinter TO test;

-- Create monitoring_spec table
CREATE TABLE IF NOT EXISTS sm_00002_vku_sinter.monitoring_spec
(
    spec_uuid uuid NOT NULL,
    process_id text,
    use_case_name text,
    spec_name text,
    device_id text,
    station_ref text,
    clamping_ref text,
    phase_ref text,
    spec_schema text,
    spec_json jsonb,
    updated_at timestamp with time zone DEFAULT now(),
    updated_by text,
    xlsx_file bytea,
    CONSTRAINT metadata_version_pkey PRIMARY KEY (spec_uuid)
);

GRANT ALL ON TABLE sm_00002_vku_sinter.monitoring_spec TO test;

-- Create scalar_measurements hypertable
CREATE TABLE IF NOT EXISTS sm_00002_vku_sinter.scalar_measurements
(
    batch_ref text COLLATE pg_catalog."default",
    order_id text COLLATE pg_catalog."default",
    material_id text COLLATE pg_catalog."default",
    program_ref text COLLATE pg_catalog."default",
    device_id text COLLATE pg_catalog."default",
    station_ref text COLLATE pg_catalog."default",
    clamping_ref text COLLATE pg_catalog."default",
    process_id text COLLATE pg_catalog."default",
    recorded_at timestamp with time zone NOT NULL,
    measurement_id uuid NOT NULL,
    metric_name text COLLATE pg_catalog."default",
    unit text COLLATE pg_catalog."default",
    metric_value numeric,
    metric_string_value text COLLATE pg_catalog."default",
    applied_detector text COLLATE pg_catalog."default",
    assigned_detector_result text COLLATE pg_catalog."default",
    usecase_id text COLLATE pg_catalog."default",
    phase_ref text COLLATE pg_catalog."default"
);

GRANT ALL ON TABLE sm_00002_vku_sinter.scalar_measurements TO test;

-- Create series_measurements hypertable
CREATE TABLE IF NOT EXISTS sm_00002_vku_sinter.series_measurements
(
    recorded_at timestamp with time zone NOT NULL,
    device_id text COLLATE pg_catalog."default",
    material_id text COLLATE pg_catalog."default",
    order_id text COLLATE pg_catalog."default",
    program_ref text COLLATE pg_catalog."default",
    batch_ref text COLLATE pg_catalog."default",
    phase_ref text COLLATE pg_catalog."default",
    station_ref text COLLATE pg_catalog."default",
    clamping_ref text COLLATE pg_catalog."default",
    metric_name text COLLATE pg_catalog."default",
    json_values jsonb,
    process_id text COLLATE pg_catalog."default",
    measurement_id uuid,
    usecase_id text COLLATE pg_catalog."default",
    additional_phase_ref text COLLATE pg_catalog."default",
    applied_detector text COLLATE pg_catalog."default",
    assigned_detector_result text COLLATE pg_catalog."default"
);

GRANT ALL ON TABLE sm_00002_vku_sinter.series_measurements TO test;

-- Create indexes
CREATE INDEX IF NOT EXISTS scalar_measurements_recorded_at_idx
    ON sm_00002_vku_sinter.scalar_measurements USING btree
    (recorded_at DESC NULLS FIRST);

CREATE INDEX IF NOT EXISTS series_measurements_recorded_at_idx
    ON sm_00002_vku_sinter.series_measurements USING btree
    (recorded_at DESC NULLS FIRST);

-- Convert tables to hypertables
SELECT create_hypertable('sm_00002_vku_sinter.scalar_measurements', by_range('recorded_at', INTERVAL '1 day'));
SELECT create_hypertable('sm_00002_vku_sinter.series_measurements', by_range('recorded_at', INTERVAL '1 day'));

To verify the monitoring_spec table run this cmd
+ SELECT * FROM sm_00002_vku_sinter.monitoring_spec;

and the result should look like this 
 spec_uuid | process_id | use_case_name | spec_name | device_id | station_ref | clamping_ref | phase_ref | spec_schema | spec_json | updated_at | updated_by | xlsx_file
-----------+------------+---------------+-----------+-----------+-------------+--------------+-----------+-------------+-----------+------------+------------+-----------
(0 rows)

To view kafka content (view the data generated by data feeder)
docker exec -it kafka /usr/bin/kafka-topics --bootstrap-server localhost:9092 --list
docker exec -it kafka /usr/bin/kafka-console-consumer --bootstrap-server localhost:9092 --topic flink-source --from-beginning true

IV. Setup data feeder
Data feeder is a pod in this kubernetes cluster which is commanded out by default. 
The operation of this pod need to be taken care since the rate that this pod generate data can overburden your disk.
If you want to run this pod to generate sample data into Kafka, move into /flink_postgres_kafka_infra/argocd_central/k8s/Flink_Infrastructure-application-mode-dev-manifest/templates/kafka-producer.yaml and undo command out the code.
After that, you just need to commit that change into the registry, then the argocd will automatically detect and spawn the corresponding pod.
I advise you to only activate this pod for a glance.