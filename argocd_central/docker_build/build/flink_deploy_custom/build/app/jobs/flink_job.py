import sys
from pathlib import Path
import json
import uuid
from typing import Dict, Any, List
from pyflink.common.typeinfo import Types
from pyflink.common.watermark_strategy import WatermarkStrategy
from pyflink.datastream import StreamExecutionEnvironment, DataStream
from abc import ABC, abstractmethod
from datetime import datetime
import pytz
import traceback
from pyflink.datastream.connectors.jdbc import JdbcConnectionOptions, JdbcExecutionOptions, JdbcSink
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common import Row
from pyflink.datastream.connectors.kafka import KafkaSource, KafkaOffsetsInitializer
from dataclasses import astuple, dataclass
from copy import deepcopy

@dataclass
class ErrorLogInternalData:
    raw_data: str
    current_data: str
    usecase: str
    transformation_id: str
    error: str
    timestamp: datetime

def get_utcoffset_of_timezone(timestamp: str, time_zone: str = None):
    ts = timestamp
    if ts[-1] == "Z":
        ts = ts.replace("Z", "+00:00")
        
    if time_zone == None:
        ts_zone = ts[-6:]
        ts_without_time_zone = ts[:-6]

        if len(ts_without_time_zone) > 26:
            ts_without_time_zone = ts_without_time_zone[:26]

        datetime_without_zone = datetime.strptime(
            ts_without_time_zone, "%Y-%m-%dT%H:%M:%S.%f"
        )
    else:
        ts_zone = time_zone
        if ts[-1] == "Z":
            ts_without_time_zone = ts[:-1]
        else:
            ts_without_time_zone = ts
        try:
            datetime_without_zone = datetime.strptime(
                ts_without_time_zone, "%Y-%m-%dT%H:%M:%S.%f"
            )
        except Exception:
            datetime_without_zone = datetime.strptime(
                ts_without_time_zone, "%Y-%m-%dT%H:%M:%S.%f%z"
            )

    datetime_with_zone = datetime.strptime(
        ts_without_time_zone + ts_zone, "%Y-%m-%dT%H:%M:%S.%f%z"
    )
    utc_time = datetime_without_zone - datetime_with_zone.utcoffset()
    return utc_time

def get_nested_value_from_dict(dictionary, *keys):
    current = dictionary
    for key in keys:
        current = current.get(key, {})
    return current

def convert_to_flinkdatarow(type_str):
    def type_str_to_flink(t_str):
        array = t_str.split("-")
        if array[1] == "text":
            return [Types.STRING() for _ in range(int(array[0]))]
        elif array[1] == "timestamptz":
            return [Types.SQL_TIMESTAMP() for _ in range(int(array[0]))]
        elif array[1] == "double":
            return [Types.DOUBLE() for _ in range(int(array[0]))]
    types_lst = []
    for e in type_str.split(","):
        types_lst.extend(type_str_to_flink(e))
    return Types.ROW(types_lst)

class PipelineConfigFactory(ABC):
    @property
    @abstractmethod
    def config_internal(self):
        pass
    
    @property
    @abstractmethod
    def config_pipeline(self):
        pass

    @abstractmethod
    def create_default_pipeline_env(self) -> StreamExecutionEnvironment:
        pass

class TransformationAbstract(ABC):
    @abstractmethod
    def apply(self, *streams, config: Dict = None) -> DataStream:
        pass

class FlinkTransformationWiring(ABC):
    def __init__(self):
        self.mapper = {}
        
    def create_transformation(self, t_name):
        return self.mapper[t_name]()

    def map_transformations(self, container):
        self.mapper = {
            "nan_str_replacement": container.nan_string_replace,
            "parse_kafka_message": container.parse_kafka_message,
            "filter_stream_main": container.filter_stream_main,
            "filter_stream_error": container.filter_stream_error,
            "error_flink_datarow": container.error_flink_datarow,
            "main_flink_datarow": container.main_flink_datarow,
            "param_extract_compose": container.param_extract_compose,
            "scalar_stream_filter": container.scalar_stream_filter,
            "series_stream_filter": container.series_stream_filter,
        }
        return self.mapper

class FlinkSourceFactory(ABC):
    @abstractmethod
    def create_source(self, config: Dict) -> Any:
        pass

class FlinkSinkFactory(ABC):
    @abstractmethod
    def create_sink(self, config: Dict) -> Any:
        pass

class SourceSinkManagerFactory(ABC):
    def __init__(self, config: PipelineConfigFactory):
        self.config = config

    @abstractmethod
    def get_sources(self, config: PipelineConfigFactory) -> Dict[str, FlinkSourceFactory]:
        pass

    @abstractmethod
    def get_sinks(self, config: PipelineConfigFactory) -> Dict[str, FlinkSinkFactory]:
        pass

class PipelineBuilderFactory(ABC):
    def __init__(self, pipeline_config: PipelineConfigFactory,
                 sinksourcemanager: SourceSinkManagerFactory,
                 transform_factory: FlinkTransformationWiring) -> None:
        self.pipeline_config = pipeline_config
        self.sinksourcemanager = sinksourcemanager
        self.transform_factory = transform_factory
        self.datastream = None

    def chain(self, transformation_name, *streams, **config):
        t_instance = self.transform_factory.create_transformation(transformation_name)
        if not streams:
            self.datastream = t_instance.apply(self.datastream, **config)
        else:
            self.datastream = t_instance.apply(*streams, **config)
        return self
    
    def finish_chain(self):
        return self.datastream

    @abstractmethod
    def build_pipeline(self):
        pass

class SourceSinkManager(SourceSinkManagerFactory):
    def get_sources(self, config: PipelineConfigFactory) -> Dict[str, FlinkSourceFactory]:
        sources = {}
        for name, source_cfg in config.config_internal["Sources"].items():
            if source_cfg["type"] == "kafka":
                obj = FlinkSourceKafkaImplV2()
                sources[name] = obj.create_source(source_cfg)
        return sources

    def get_sinks(self, config: PipelineConfigFactory) -> Dict[str, FlinkSinkFactory]:
        sinks = {}
        for name, sink_cfg in config.config_internal["Sinks"].items():
            obj = FlinkSinkImplPostgres()
            sinks[name] = obj.create_sink(sink_cfg)
        return sinks

class FlinkSourceKafkaImplV2(FlinkSourceFactory):
    def create_source(self, config: Dict) -> KafkaSource:
        kafka_props = config["config"]
        topic = config["topic_name"]
        group_id = kafka_props.get("group.id", "forward-only")

        source_builder = KafkaSource.builder() \
            .set_bootstrap_servers(kafka_props["bootstrap.servers"]) \
            .set_topics(topic) \
            .set_group_id(group_id) \
            .set_value_only_deserializer(SimpleStringSchema())

        if config["latest_offset"]:
            starting_offsets = KafkaOffsetsInitializer.latest()
        else:
            starting_offsets = KafkaOffsetsInitializer.earliest()

        source_builder.set_starting_offsets(starting_offsets)
        return source_builder.build()

class FlinkSinkImplPostgres(FlinkSinkFactory):
    def create_sink(self, config):
        jdbc_props = config["config"]
        type_info = convert_to_flinkdatarow(jdbc_props["types_str"])

        user_name = jdbc_props['user']
        password = jdbc_props['password']

        jdbc_sink = JdbcSink.sink(
            jdbc_props['sql_statement'], 
            type_info,
            JdbcConnectionOptions.JdbcConnectionOptionsBuilder().with_url(
                f"{jdbc_props['connectionstring']}/{jdbc_props['database']}").with_driver_name(jdbc_props['driver']).
            with_user_name(user_name).with_password(password).build(),
            JdbcExecutionOptions.builder().with_batch_interval_ms(
                int(jdbc_props['insertbatchinterval'])).with_batch_size(
                    int(jdbc_props['batchsize'])).with_max_retries(int(jdbc_props['retries'])).build())

        return jdbc_sink

class MapDataToFlinkRow(TransformationAbstract):
    def apply(self, *streams, config) -> DataStream:
        config_jdbc_dct = config["config"]
        rows = convert_to_flinkdatarow(config_jdbc_dct["types_str"])
        return streams[0].map(lambda t: Row(*t), output_type=rows)

class MapErrorDataToFlinkRow(TransformationAbstract):
    def apply(self, *streams, config=None) -> DataStream:
        config_jdbc_dct = config["Sinks"]["JDBCSinkError"]["config"]
        rows = convert_to_flinkdatarow(config_jdbc_dct["types_str"])
        return streams[0].flat_map(lambda x: (item for item in x[2])).map(lambda x: astuple(x)).map(lambda t: Row(*t), output_type=rows)

class FilterStreamMain(TransformationAbstract):
    def apply(self, *streams) -> DataStream:
        return streams[0].filter(lambda x: x[1] == False)

class FilterStreamError(TransformationAbstract):
    def apply(self, *streams) -> DataStream:
        return streams[0].filter(lambda x: x[1] == True)

class NanStringReplacementImpl(TransformationAbstract):
    def apply(self, *streams) -> DataStream:
        def __nanStrReplace(raw_json_str: str):
            return raw_json_str.replace(": NaN,", ': "NaN",').replace(": NaN", ': "NaN"')
        return streams[0].map(__nanStrReplace)

class ParseKafkaMessage(TransformationAbstract):
    def __json_parse(self, data):
        error_flag = False
        try:
            dict_data = json.loads(data)
            return (dict_data, error_flag, None)
        except Exception as e:
            full_msg = str(e) + "\n" + traceback.format_exc()
            current_time = datetime.now()
            data_pass = ErrorLogInternalData(data, data, "UC-x", "RAW", full_msg, current_time)
            error_flag = True
            return (data, error_flag, [data_pass])
        
    def apply(self, *streams) -> DataStream:
        return streams[0].map(self.__json_parse)

class ParamExtractAndCompose(TransformationAbstract):
    def __convert_dict_element_to_str(self, tuple_data):
        return tuple(json.dumps(item) if isinstance(item, dict) else item for item in tuple_data)
        
    def __convert_to_list_tuple(self, json_section_dct, is_series, usecase_id, extra_params=None):
        param_list = []
        for key, values_dct in json_section_dct.items():
            tple = ()
            if is_series:
                values = (json.dumps(values_dct), )
            else:
                if isinstance(values_dct.get("value"), str):
                    value = values_dct["value"]
                    values_dct["value"] = None
                    values_dct["value_string"] = value
                else:
                    values_dct["value_string"] = None
                values = (values_dct.get("unit"), values_dct.get("value"), values_dct.get("value_string"), None, None)
            tple = (str(uuid.uuid4()), key) + values + (usecase_id,)
            if extra_params is None:
                tple += (None, None, None,)
            else:
                tple += tuple(extra_params)
            param_list.append(self.__convert_dict_element_to_str(tple))
        return param_list

    def __extract_metric_params(self, json_data, sinks_config_dict, config_section, is_series):
        uc_id = sinks_config_dict["USECASE"]["id"]
        parent_key = sinks_config_dict[config_section]["parent_key"]
        json_section = get_nested_value_from_dict(json_data, *parent_key.split('.')) or {}
        config_extra = deepcopy(sinks_config_dict[config_section])
        del config_extra["parent_key"]
        extra_params = []
        for key_target, val in config_extra.items():
            if val == "":
                extra_params.append(get_nested_value_from_dict(json_data, *key_target.split('.')))
            else:
                extra_params.append(None)
        return self.__convert_to_list_tuple(json_section, is_series, uc_id, extra_params)

    def __extract_meta_param(self, json_data, sinks_config_dict, config_section_meta):
        param_meta_section = sinks_config_dict[config_section_meta]
        def value_convert_and_extract(value):
            if value == "--None--/key":
                return "generated_" + str(uuid.uuid4())
            elif value == "--None--/value":
                return {}
            else:
                reduced_val = get_nested_value_from_dict(json_data, *value.split('.'))
            if value == "process.recordedAt":
                return get_utcoffset_of_timezone(reduced_val)
            if value == "process":
                dict_val = deepcopy(reduced_val)
                del dict_val["parameters"]
                del dict_val["recordedAt"]
                return dict_val
            if value == "part":
                dict_val = deepcopy(reduced_val)
                del dict_val["program"]
                del dict_val["station"]
                return dict_val
            return reduced_val
        tuple_meta_param = tuple(value_convert_and_extract(v) for v in param_meta_section)
        return self.__convert_dict_element_to_str(tuple_meta_param)

    def __compose_data_list(self, scalar_param_list, series_param_list, meta_tuple):
        return {
            "scalar": [meta_tuple + t for t in scalar_param_list],
            "series": [meta_tuple + t for t in series_param_list]
        }

    def __validation_check(self, data_dict):
        SCALAR_PARAM_NUM = 18
        SERIES_PARAM_NUM = 14
        valid = True
        for v in data_dict.get("scalar", []):
            if len(v) != SCALAR_PARAM_NUM:
                print(f"Missing SCALAR parameters, expected {SCALAR_PARAM_NUM}, got {len(v)}")
                valid = False
        for v in data_dict.get("series", []):
            if len(v) != SERIES_PARAM_NUM:
                print(f"Missing SERIES parameters, expected {SERIES_PARAM_NUM}, got {len(v)}")
                valid = False
        return valid

    def __extract_compose(self, incomming_json_data, config):
        sinks_config_dict = config["TRANSFORMATION"]["sinks_config"]
        meta_params_tuple = self.__extract_meta_param(incomming_json_data, sinks_config_dict, "META_PARAMS")
        scalar_params_list = self.__extract_metric_params(incomming_json_data, sinks_config_dict, "SCALAR_PARAMS", False)
        series_params_list = self.__extract_metric_params(incomming_json_data, sinks_config_dict, "SERIES_PARAMS", True)
        data_dict = self.__compose_data_list(scalar_params_list, series_params_list, meta_params_tuple)
        error_flag = self.__validation_check(data_dict)
        return (data_dict, error_flag)

    def apply(self, *streams, config: Dict) -> DataStream:
        return streams[0].map(lambda x: self.__extract_compose(x, config)).filter(lambda x: x[1]).map(lambda x: x[0])

class ScalarMetricStreamFiltering(TransformationAbstract):
    def apply(self, *streams) -> DataStream:
        return streams[0].filter(lambda x: 'scalar' in x).map(lambda x: x['scalar']).flat_map(lambda x: (item for item in x))

class SeriesMetricStreamFiltering(TransformationAbstract):
    def apply(self, *streams) -> DataStream:
        return streams[0].filter(lambda x: 'series' in x).map(lambda x: x['series']).flat_map(lambda x: (item for item in x))

class Pipeline(PipelineBuilderFactory):
    def build_pipeline(self):
        pipeline_env = self.pipeline_config.create_default_pipeline_env()
        sources = self.sinksourcemanager.get_sources(self.pipeline_config)
        sinks_pipeline = self.sinksourcemanager.get_sinks(self.pipeline_config)
        self.transform_factory.map_transformations(ContainerWiring())
        pipeline_env.enable_checkpointing(10000)

        streams = []
        mapper = {}

        def map_sinks_to_sources(source_name):
            sinks = {}
            for sink_name, sink_cfg in self.pipeline_config.config_internal["Sinks"].items():
                if sink_cfg.get("source") == source_name:
                    sinks[sink_cfg["datatype"]] = {"sink_obj": sinks_pipeline[sink_name], "config": sink_cfg}
            return sinks

        for name, source_obj in sources.items():
            streams.append(pipeline_env.from_source(source_obj, WatermarkStrategy.no_watermarks(), name))
            mapper[name] = map_sinks_to_sources(name)

        if not streams:
            raise ValueError("No streams to union")
        stream = streams[0]
        for s in streams[1:]:
            stream = stream.union(s)

        stream_transform = self.chain("nan_str_replacement", stream)\
            .chain("parse_kafka_message").finish_chain()

        stream_main = self.chain("filter_stream_main", stream_transform).finish_chain()
        stream_error = self.chain("filter_stream_error", stream_transform)\
            .chain("error_flink_datarow", config=self.pipeline_config.config_internal).finish_chain()
        
        stream_error.add_sink(sinks_pipeline["JDBCSinkError"])
        stream_main = stream_main.map(lambda x: x[0])

        for source_name, sinks_stream in mapper.items():
            stream_individual = stream_main.filter(lambda x: x.get("process", {}).get("id") == source_name)
            stream_processed = self.chain("param_extract_compose", stream_individual, config=self.pipeline_config.config_pipeline).finish_chain()
            scalar_stream = self.chain("scalar_stream_filter", stream_processed).finish_chain()
            series_stream = self.chain("series_stream_filter", stream_processed).finish_chain()

            if not sinks_stream:
                print(f"No sinks for source: {source_name}")
                continue

            try:
                scalar_config = sinks_stream['scalar']['config']
                series_config = sinks_stream['series']['config']
                scalar_stream = self.chain("main_flink_datarow", scalar_stream, config=scalar_config).finish_chain()
                series_stream = self.chain("main_flink_datarow", series_stream, config=series_config).finish_chain()
                scalar_stream.add_sink(sinks_stream['scalar']['sink_obj'])
                series_stream.add_sink(sinks_stream['series']['sink_obj'])
            except Exception as e:
                print(f"Failed to attach sinks for {source_name}: {e}")

        pipeline_env.execute("Local Flink Forwarder Job")

class ContainerWiring:
    def __init__(self):
        self.filter_stream_main = FilterStreamMain
        self.filter_stream_error = FilterStreamError
        self.error_flink_datarow = MapErrorDataToFlinkRow
        self.main_flink_datarow = MapDataToFlinkRow
        self.parse_kafka_message = ParseKafkaMessage
        self.nan_string_replace = NanStringReplacementImpl
        self.param_extract_compose = ParamExtractAndCompose
        self.scalar_stream_filter = ScalarMetricStreamFiltering
        self.series_stream_filter = SeriesMetricStreamFiltering

class PipelineConfigImpl(PipelineConfigFactory):
    def __init__(self):
        self._config_internal = {
            "Sources": {
                "00002_vku_sinter": {
                    "type": "kafka",
                    "topic_name": "00002-vku-sinter_inbound-batchMeasurement",
                    "data_format": "text",
                    "latest_offset": True,
                    "source_implementation": "FlinkSourceKafkaImplV2",
                    "bootstrap_servers": "172.17.0.1:9092",
                    "config": {
                        "group.id": "00002-vku-sinter-forward-only",
                        "bootstrap.servers": "172.17.0.1:9092"
                    }
                }
            },
            "Sinks": {
                "JDBCSinkError": {
                    "type": "jdbc",
                    "datatype": "error",
                    "sink_implementation": "FlinkSinkImplPostgres",
                    "source": "00002_vku_sinter",
                    "config": {
                        "types_str": "5-text,1-timestamptz",
                        "sql_statement": "INSERT INTO sm_base.error_log(raw_data, current_data, usecase, transformation_id, error, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                        "database": "smart_monitoring_db",
                        "connectionstring": "jdbc:postgresql://172.17.0.1:5432",
                        "driver": "org.postgresql.Driver",
                        "user": "test",
                        "password": "password",
                        "insertbatchinterval": 100,
                        "batchsize": 500,
                        "retries": 5
                    }
                },
                "JDBC02ScalarSink": {
                    "source": "00002_vku_sinter",
                    "type": "jdbc",
                    "datatype": "scalar",
                    "sink_implementation": "FlinkSinkImplPostgres",
                    "config": {
                        "types_str": "8-text,1-timestamptz,3-text,1-double,5-text",
                        "sql_statement": "INSERT INTO sm_00002_vku_sinter.scalar_measurements (batch_ref, order_id, material_id, program_ref, device_id, station_ref, clamping_ref, process_id, recorded_at, measurement_id, metric_name, unit, metric_value, metric_string_value, applied_detector, assigned_detector_result, usecase_id, phase_ref) VALUES (?::text, ?::text, ?::text, ?::text, ?::text, ?::text, ?::text, ?::text, ?::timestamptz, ?::uuid, ?::text, ?::text, ?::numeric, ?::text, ?::text, ?::text, ?::text, ?::text);",
                        "database": "smart_monitoring_db",
                        "connectionstring": "jdbc:postgresql://172.17.0.1:5432",
                        "driver": "org.postgresql.Driver",
                        "user": "test",
                        "password": "password",
                        "insertbatchinterval": 1000,
                        "batchsize": 200,
                        "retries": 5
                    }
                },
                "JDBC02SeriesSink": {
                    "source": "00002_vku_sinter",
                    "type": "jdbc",
                    "datatype": "series",
                    "sink_implementation": "FlinkSinkImplPostgres",
                    "config": {
                        "types_str": "8-text,1-timestamptz,5-text",
                        "sql_statement": "INSERT INTO sm_00002_vku_sinter.series_measurements (batch_ref, order_id, material_id, program_ref, device_id, station_ref, clamping_ref, process_id, recorded_at, measurement_id, metric_name, json_values, usecase_id, phase_ref) VALUES (?::text, ?::text, ?::text, ?::text, ?::text, ?::text, ?::text, ?::text, ?::timestamptz, ?::uuid, ?::text, ?::jsonb, ?::text, ?::text);",
                        "database": "smart_monitoring_db",
                        "connectionstring": "jdbc:postgresql://172.17.0.1:5432",
                        "driver": "org.postgresql.Driver",
                        "user": "test",
                        "password": "password",
                        "insertbatchinterval": 1000,
                        "batchsize": 200,
                        "retries": 5
                    }
                }
            }
        }
        self._config_pipeline = {
            "Pipeline": {
                "Max_Parallelism": 5
            },
            "JARS": [
                "flink-sql-connector-kafka-3.2.0-1.18.jar",
                "flink-connector-jdbc-3.1.1-1.17.jar",
                "postgresql-42.7.0.jar"
            ],
            "TRANSFORMATION": {
                "sinks_config": {
                    "USECASE": {
                        "id": "forwarder"
                    },
                    "META_PARAMS": [
                        "batch.name",
                        "batch.productionOrder",
                        "batch.material",
                        "batch.program.name",
                        "device.id",
                        "station.name",
                        "station.clampingUnit",
                        "process.id",
                        "process.recordedAt"
                    ],
                    "SCALAR_PARAMS": {
                        "parent_key": "process.parameters.scalar",
                        "process.trace.value": ""
                    },
                    "SERIES_PARAMS": {
                        "parent_key": "process.parameters.series",
                        "process.trace.value": ""
                    }
                }
            }
        }

    @property
    def config_internal(self):
        return self._config_internal

    @property
    def config_pipeline(self):
        return self._config_pipeline

    def create_default_pipeline_env(self) -> StreamExecutionEnvironment:
        env = StreamExecutionEnvironment.get_execution_environment()
        env.set_max_parallelism(5)
        env.add_jars(
            "file:///opt/flink/lib/flink-sql-connector-kafka-3.2.0-1.18.jar",
            "file:///opt/flink/lib/flink-connector-jdbc-3.1.1-1.17.jar",
            "file:///opt/flink/lib/postgresql-42.7.0.jar"
        )
        return env

if __name__ == "__main__":
    transformations = FlinkTransformationWiring()
    pipeline_config = PipelineConfigImpl()
    sinksourcemanager = SourceSinkManager(pipeline_config)
    pipeline = Pipeline(pipeline_config, sinksourcemanager, transformations)
    pipeline.build_pipeline()