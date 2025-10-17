import json
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Any
import uuid

from kafka import KafkaProducer

SLEEP_TIME = 0.5

def generate_time_series(start_time, length, interval_ms=100):
    return [start_time + (i * interval_ms) / 1000 for i in range(length)]

def generate_force_series(length):
    forces = []
    initial_force = random.uniform(570, 580)
    for i in range(length):
        if i < 20:
            force = initial_force + i * random.uniform(0.5, 1.5)
        elif i < 40:
            force = initial_force + 20 + random.uniform(-2, 2)
        elif i < 60:
            force = initial_force + 20 - (i - 20) * random.uniform(0.5, 1)
        elif i < 80:
            force = initial_force - 10 + random.uniform(-0.5, 0.5)
        else: 
            force = 0.0
        forces.append(round(force, 5))
    return forces

def generate_distance_series(length):
    distances = []
    initial_distance = random.uniform(-100, -80)
    for i in range(length):
        if i < 20:
            distance = initial_distance - i * random.uniform(100, 200)
        elif i < 40:
            distance = distances[-1] - random.uniform(50, 100) if distances else initial_distance
        elif i < 60:
            distance = distances[-1] + random.uniform(50, 100) if distances else initial_distance
        elif i < 80:
            distance = distances[-1] + random.uniform(-10, 10) if distances else initial_distance
        else:
            distance = 0.0
        distances.append(round(distance))
    return distances

def generate_info_ascii_series(length):
    info = [0] * length
    non_zero_indices = random.sample(range(40, 60), 3)
    for idx in non_zero_indices:
        info[idx] = random.randint(65, 90)
    return info

def generate_sensor_data() -> dict[str, Any]:
    """Generates random sensor data matching the provided format with time series and metadata."""
    current_time = datetime.now(timezone(timedelta(hours=2))).isoformat()
    series_length = 300
    time_series = generate_time_series(0.099, series_length)

    sensor_data = {
        "id": str(uuid.uuid4()),
        "dataModel": {
            "id": f"00002_vku_sinter_{datetime.now().isoformat()}",
            "type": "singlePiece",
            "state": "TEST"
        },
        "device": {
            "id": "10031033",
            "giai": "405497280000000000345021",
            "mesId": "UNKNOWN",
            "machineName": "IDS-2.4",
            "plant": "RvP",
            "valueStream": "UNKNOWN",
            "location": "UNKNOWN",
            "building": "UNKNOWN",
            "level": "UNKNOWN",
            "organizationalUnit": "UNKNOWN",
            "workCenter": "UNKNOWN",
            "machineCluster": "UNKNOWN",
            "workUnit": "UNKNOWN"
        },
        "batch": {
            "name": "UNKNOWN",
            "material": "UNKNOWN",
            "productionOrder": "UNKNOWN",
            "handlingUnit": None,
            "program": {
                "name": "10,00-09,40-Plus7X-Plus7X-42/4 FLP",
                "version": "UNKNOWN"
            }
        },
        "station": {
            "name": "4",
            "clampingUnit": "unknown"
        },
        "process": {
            "id": "00002_vku_sinter",
            "description": "welding/brazing process of drill bits with copper solder",
            "trace": {
                "type": "part",
                "value": None
            },
            "parameters": {
                "scalar": {
                    "timeSinceLastPart": {"value": None, "unit": "s"},
                    "errorState": {"value": None, "unit": ""},
                    "errorType": {"value": None, "unit": ""},
                    "errorNumber": {"value": None, "unit": ""},
                    "errorEvent": {"value": None, "unit": ""},
                    "powerSet": {"value": 47, "unit": "%"},
                    "currentSet": {"value": 200, "unit": "A"},
                    "weldingPosSet": {"value": -6.5, "unit": "mm"},
                    "powerMax": {"value": 47, "unit": "%"},
                    "currentMax": {"value": 57, "unit": "A"},
                    "frequencyMax": {"value": 249.2, "unit": "kHz"},
                    "distanceMax": {"value": 0.54843, "unit": "mm"},
                    "chargeMax": {"value": 3346, "unit": None},
                    "energyMax": {"value": 8.3849, "unit": None},
                    "shutoffForce": {"value": 558.5657, "unit": "N"},
                    "shutoffDist": {"value": 0.22588999569416046, "unit": "mm"},
                    "shutoffTime": {"value": 5.13, "unit": "s"},
                    "weldingPos": {"value": -6.2684, "unit": "mm"},
                    "lengthDrillBit": {"value": 161, "unit": "mm"},
                    "stationCounter": {"value": 976, "unit": "pcs"}
                },
                "series": {
                    "force": {
                        "values": generate_force_series(series_length),
                        "valuesUnit": "N",
                        "relativeRecordingTimes": time_series,
                        "timesUnit": "ms"
                    },
                    "distance": {
                        "values": generate_distance_series(series_length),
                        "valuesUnit": "mm",
                        "relativeRecordingTimes": time_series,
                        "timesUnit": "ms"
                    },
                    "infoACII": {
                        "values": generate_info_ascii_series(series_length),
                        "valuesUnit": None,
                        "relativeRecordingTimes": time_series,
                        "timesUnit": "ms"
                    }
                }
            },
            "recordedAt": current_time
        }
    }
    return sensor_data



def main() -> None:
    """
    Controls the flow of the producer. It first subscribes to the topic and then
    generates sensor data and sends it to the topic.
    """
    bootstrap_servers = '172.17.0.1:9092'
    topic = 'flink-source'
    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    
    while True:
        sensor_data = generate_sensor_data()
        producer.send(topic, value=sensor_data)
        print(f"Produced to {topic}: {sensor_data['id']}")
        time.sleep(SLEEP_TIME)


if __name__ == "__main__":
    main()