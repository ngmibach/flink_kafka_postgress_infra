

# Setup Guide for Kubernetes, ArgoCD, Flink, Kafka, and PostgresDB

This guide provides instructions for setting up a Kubernetes environment with ArgoCD, Flink Kubernetes Operator, Kafka, PostgresDB, and a data feeder. Ensure you have Docker, `kubectl`, `helm`, and a local Kubernetes cluster (e.g., Docker Desktop, Minikube) installed before proceeding. **Note:** If you have ArgoCD, k9s, a local registry, Kafka, or PostgresDB running, please shut them down to avoid conflicts.

## Prerequisites
- Docker and Docker Compose
- `kubectl` and `helm` CLI tools
- Access to a Kubernetes cluster
- Access to the Bosch Artifactory for Flink images (requires credentials)
- Git for repository initialization
- Basic knowledge of Kubernetes, ArgoCD, and Helm

## 1. Setting Up Kubernetes and ArgoCD

### Startup
1. Run the following command to start the necessary services:
   ```bash
   docker compose up -d
   ```
2. Once the services are up, navigate to the `argocd_central` directory and execute:
   ```bash
   bash init.sh
   ```
   This script builds a custom image and initializes the Git repository for ArgoCD.

### Accessing ArgoCD
1. Retrieve the ArgoCD admin password:
   ```bash
   kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
   ```
2. Access the following services in your browser:
   - **ArgoCD**: `https://localhost:30001`
   - **KubeOpsView**: `http://localhost:30002`
   - **App Example**: `http://localhost:30000`

### Rebuilding the Example Application
To rebuild the `appexample` application with a new timestamp-based image:
1. Navigate to the `app-example` directory.
2. Run:
   ```bash
   bash build-image.sh
   ```

### Quick Setup
For a streamlined setup, execute:
```bash
bash full_up.sh
```

## 2. Setting Up Flink Kubernetes Operator

The Flink Kubernetes Operator requires images from the Bosch Artifactory. Follow these steps:

1. Log in to the Bosch Artifactory:
   ```bash
   docker login radium-pt-ac-smartqm-docker-release-local.rb-artifactory.bosch.com
   ```
2. Pull the required images:
   ```bash
   docker pull radium-pt-ac-smartqm-docker-release-local.rb-artifactory.bosch.com/flink/flink-deployments:flink-kubernetes-operator
   docker pull radium-pt-ac-smartqm-docker-release-local.rb-artifactory.bosch.com/flink/flink-deployments:flink-main-container-v119-aws
   ```
3. Navigate to `flink_postgres_kafka_infra/argocd_central/docker_build` and build/push the images:
   ```bash
   docker compose build
   docker compose push
   ```

   **Optional**: To skip running Flink jobs and focus on the Kubernetes setup, comment out the following services in `docker-compose.yaml`:
   ```yaml
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
   ```

4. Install the cert-manager for Flink:
   ```bash
   kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.19.1/cert-manager.yaml
   ```

5. If the Flink Kubernetes Operator does not install correctly, manually install it using Helm:
   ```bash
   helm repo add flink-operator-repo https://downloads.apache.org/flink/flink-kubernetes-operator-1.13.0/
   helm repo update
   helm install flink-kubernetes-operator flink-operator-repo/flink-kubernetes-operator -n workspace
   ```

## 3. Setting Up Kafka Source and PostgresDB Sink

### Kafka and PostgresDB Setup
1. Navigate to `flink_postgres_kafka_infra/kafka` and start the services:
   ```bash
   docker compose up -d
   ```

2. Attach a shell to the Postgres container and connect to the database:
   ```bash
   psql -U test -d smart_monitoring_db
   ```

3. Execute the following SQL commands to create the schema and tables:

   ```sql
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
   ```

4. Verify the `monitoring_spec` table:
   ```sql
   SELECT * FROM sm_00002_vku_sinter.monitoring_spec;
   ```
   Expected output:
   ```
   spec_uuid | process_id | use_case_name | spec_name | device_id | station_ref | clamping_ref | phase_ref | spec_schema | spec_json | updated_at | updated_by | xlsx_file
   -----------+------------+---------------+-----------+-----------+-------------+--------------+-----------+-------------+-----------+------------+------------+-----------
   (0 rows)
   ```

### Viewing Kafka Data
To inspect Kafka topics and data:
1. List available topics:
   ```bash
   docker exec -it kafka /usr/bin/kafka-topics --bootstrap-server localhost:9092 --list
   ```
2. View data from the `flink-source` topic:
   ```bash
   docker exec -it kafka /usr/bin/kafka-console-consumer --bootstrap-server localhost:9092 --topic flink-source --from-beginning
   ```

## 4. Setting Up the Data Feeder

The data feeder is a Kubernetes pod that generates sample data for Kafka. It is disabled by default to prevent excessive disk usage.

1. To enable the data feeder, navigate to:
   ```
   flink_postgres_kafka_infra/argocd_central/k8s/Flink_Infrastructure-application-mode-dev-manifest/templates/kafka-producer.yaml
   ```
2. Uncomment the code in `kafka-producer.yaml`.
3. Commit the changes to the Git repository. ArgoCD will automatically detect the change and deploy the pod.
4. **Caution**: Monitor the pod as it may generate large amounts of data, potentially filling up your disk. Only activate it briefly for testing purposes.

## Notes
- Ensure all services (ArgoCD, k9s, local registry, Kafka, PostgresDB) are stopped before starting the setup to avoid port conflicts.
- The data feeder pod should be used sparingly to avoid overloading your system.
- For issues with the Flink Kubernetes Operator, verify cert-manager installation and Helm chart compatibility.
- For API-related queries or additional xAI services, visit [https://x.ai/api](https://x.ai/api).

