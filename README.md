

# Setup Guide for Kubernetes, ArgoCD, Flink, Kafka, and PostgresDB

This guide provides instructions for setting up a Kubernetes environment with ArgoCD, Flink Kubernetes Operator, Kafka, PostgresDB, and a data feeder. Ensure you have Docker installed before proceeding. **Note:** If you have ArgoCD, k9s, a local registry, Kafka, or PostgresDB running, please shut them down to avoid conflicts.

## Prerequisites
- Docker and Docker Compose
- Access right to the Bosch Artifactory for Flink images (requires credentials)

## 1. Setting Up Kubernetes and ArgoCD

### Startup
1. Run the following command to start the necessary services:
   ```bash
   docker compose up -d
   ```
2. Once the services are up, navigate to the `flink_postgres_kafka_infra/argocd_central` directory and execute:         
   ```bash
   bash init.sh 
   ```
   This script builds a custom image and initializes the Git repository for ArgoCD.

### Quick Setup
For a streamlined setup, execute:
```bash
bash full_up.sh
```

Allow 5–10 minutes for all components to initialize and deploy. Then, open another terminal and execute k9s to view the Kubernetes cluster. To access the ArgoCD server, navigate to the corresponding pod in k9s and press Shift + F to forward the port. 

Retrieve the ArgoCD admin password:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

## 2. Setting Up Flink Kubernetes Operator

The Flink Kubernetes Operator requires images from the Bosch Artifactory. Follow these steps:

1. Log in to the Bosch Artifactory:
   ```bash
   docker login radium-pt-ac-smartqm-docker-release-local.rb-artifactory.bosch.com -u <your-id> -p <your-password> 
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

4. Install the cert-manager for Flink-kubernetes-operator:
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
   -- Create sm_00002_vku_sinter schema
   CREATE SCHEMA sm_00002_vku_sinter;
   GRANT USAGE ON SCHEMA sm_00002_vku_sinter TO test;

   -- Create sm_base schema for error_log
   CREATE SCHEMA IF NOT EXISTS sm_base;
   GRANT USAGE ON SCHEMA sm_base TO test;

   -- Create scalar_measurements table
   CREATE TABLE sm_00002_vku_sinter.scalar_measurements (
      batch_ref TEXT,
      order_id TEXT,
      material_id TEXT,
      program_ref TEXT,
      device_id TEXT,
      station_ref TEXT,
      clamping_ref TEXT,
      process_id TEXT,
      recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
      measurement_id UUID NOT NULL,
      metric_name TEXT,
      unit TEXT,
      metric_value DOUBLE PRECISION,
      metric_string_value TEXT,
      applied_detector TEXT,
      assigned_detector_result TEXT,
      usecase_id TEXT,
      phase_ref TEXT
   );
   GRANT ALL ON TABLE sm_00002_vku_sinter.scalar_measurements TO test;

   -- Create series_measurements table
   CREATE TABLE sm_00002_vku_sinter.series_measurements (
      batch_ref TEXT,
      order_id TEXT,
      material_id TEXT,
      program_ref TEXT,
      device_id TEXT,
      station_ref TEXT,
      clamping_ref TEXT,
      process_id TEXT,
      recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
      measurement_id UUID,
      metric_name TEXT,
      json_values JSONB,
      usecase_id TEXT,
      phase_ref TEXT
   );
   GRANT ALL ON TABLE sm_00002_vku_sinter.series_measurements TO test;

   -- Create error_log table
   CREATE TABLE sm_base.error_log (
      raw_data TEXT,
      current_data TEXT,
      usecase TEXT,
      transformation_id TEXT,
      error TEXT,
      timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
   );
   GRANT ALL ON TABLE sm_base.error_log TO test;

   -- Create indexes for scalar_measurements and series_measurements
   CREATE INDEX scalar_measurements_recorded_at_idx
      ON sm_00002_vku_sinter.scalar_measurements USING btree
      (recorded_at DESC NULLS FIRST);

   CREATE INDEX series_measurements_recorded_at_idx
      ON sm_00002_vku_sinter.series_measurements USING btree
      (recorded_at DESC NULLS FIRST);

   -- Convert scalar_measurements and series_measurements to hypertables
   SELECT create_hypertable('sm_00002_vku_sinter.scalar_measurements', by_range('recorded_at', INTERVAL '1 day'));
   SELECT create_hypertable('sm_00002_vku_sinter.series_measurements', by_range('recorded_at', INTERVAL '1 day'));
   ```

4. To view the contents or verify the creation of the `error_log`, `series_measurements` and `scalar_measurements` table:
   1. `error_log` table:
   ```sql
   SELECT * FROM sm_base.error_log;
   ```
   Expected output:
   ```
   raw_data | current_data | usecase | transformation_id | error | timestamp 
   ----------+--------------+---------+-------------------+-------+-----------
   (0 rows)
   ```

   2. `series_measurements` table:
   ```sql
   SELECT * FROM sm_00002_vku_sinter.series_measurements;
   ```
   Expected output:
   ```
   batch_ref | order_id | material_id | program_ref | device_id | station_ref | clamping_ref | process_id | recorded_at | measurement_id | metric_name | json_values | usecase_id | phase_ref 
   -----------+----------+-------------+-------------+-----------+-------------+--------------+------------+-------------+----------------+-------------+-------------+------------+-----------
   (0 rows)
   ```

   3. `scalar_measurements` table:
   ```sql
   SELECT * FROM sm_00002_vku_sinter.scalar_measurements;
   ```
   Expected output:
   ```
   batch_ref | order_id | material_id | program_ref | device_id | station_ref | clamping_ref | process_id | recorded_at | measurement_id | metric_name | unit | metric_value | metric_string_value | applied_detector | assigned_detector_result | usecase_id | phase_ref 
   -----------+----------+-------------+-------------+-----------+-------------+--------------+------------+-------------+----------------+-------------+------+--------------+---------------------+------------------+--------------------------+------------+-----------
   (0 rows)
   ```

5. To view selected data at desired time in PostgresDB:
   ```sql
   SELECT recorded_at, metric_name, json_values 
   FROM sm_00002_vku_sinter.series_measurements 
   WHERE device_id = '10031033' 
   AND recorded_at >= NOW() - INTERVAL '1 week' 
   ORDER BY recorded_at DESC;
   ```

### Viewing Kafka Data
To inspect Kafka topics and data:
1. List available topics:
   ```bash
   docker exec -it kafka /usr/bin/kafka-topics --bootstrap-server localhost:9092 --list
   ```
2. View data from the `flink-source` topic:
   ```bash
   docker exec -it kafka /usr/bin/kafka-console-consumer --bootstrap-server localhost:9092 --topic flink-source --from-beginning true
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

## 5. Setting Up the Flink Job
Follow these steps to configure and start the Flink job:
1. Verify Required Directories

Ensure the following directories exist in your file system to support persistent volumes and Flink pod functionality:
- /home/dev/checkpoints/
- /home/dev/savepoints/
- /mnt/local-data

Create them if they do not exist:
```bash
mkdir -p /home/dev/checkpoints /home/dev/savepoints /mnt/local-data
```

2. Enable Flink Job 

Edit the reactive_mode.yaml file located at:
```
flink_postgres_kafka_infra/argocd_central/k8s/Flink_Infrastructure-application-mode-dev-manifest/templates/reactive_mode.yaml
```

Uncomment the following lines:
```yaml
jarURI: "local:///opt/flink/app/jobs/flink_job.py"
entryClass: "org.apache.flink.client.python.PythonDriver"
args: ["-py", "/opt/flink/app/jobs/flink_job.py"]
parallelism: 1
```

3. Commit and Push Change

4. Sync in ArgoCD
- Access the ArgoCD UI.
- Click the Sync button to apply the changes and start the job.

5. **Notes**
- You may need to delete the reactive-dev flink deployment pod before applying job changes
- Ensure that data feeder pod is active, since the Flink Job is configured to only consume latest data by default.


## Notes
- Ensure all your local services (ArgoCD, k9s, local registry, Kafka, PostgresDB) are stopped before starting the setup to avoid port conflicts.
- The data feeder pod should be used sparingly to avoid overloading your system.
