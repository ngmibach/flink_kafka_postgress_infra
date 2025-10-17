import json
import uuid
import os
from pyflink.common.typeinfo import Types
from pyflink.common.watermark_strategy import WatermarkStrategy
from pyflink.table import StreamTableEnvironment, EnvironmentSettings
from pyflink.datastream import DataStream, StreamExecutionEnvironment
from pyflink.datastream.connectors import JdbcSink, JdbcConnectionOptions, JdbcExecutionOptions
from pyflink.datastream.connectors.kafka import KafkaSource, KafkaOffsetsInitializer
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common import Row
from abc import ABC, abstractmethod
from dependency_injector import containers, providers
import datetime
import pytz
from copy import deepcopy

def get_config_section(config):
    return config

def get_nested_value_from_dict(data, *keys):
    current = data
    for key in keys:
        current = current.get(key, {})
    return current if current != {} else None

def get_utcoffset_of_timezone(timestamp):
    try:
        return datetime.datetime.fromisoformat(timestamp)
    except ValueError:
        return datetime.datetime.now(pytz.utc)

def convert_to_flinkdatarow(type_str):
    types = []
    for t in type_str.split(','):
        count, dtype = t.split('-')
        if dtype == 'text':
            types.extend([Types.STRING()] * int(count))
        elif dtype == 'timestamptz':
            types.extend([Types.SQL_TIMESTAMP()] * int(count))
        elif dtype == 'double':
            types.extend([Types.DOUBLE()] * int(count))
    return Types.ROW(types)

class ErrorLogInternalData:
    def __init__(self, raw_data, current_data, usecase, transformation_id, error, timestamp):
        self.raw_data = raw_data
        self.current_data = current_data
        self.usecase = usecase
        self.transformation_id = transformation_id
        self.error = error
        self.timestamp = timestamp

    def __iter__(self):
        return iter((self.raw_data, self.current_data, self.usecase, self.transformation_id, self.error, self.timestamp))

class TransformationAbstract(ABC):
    def __init__(self):
        self.outputs = {}

    @abstractmethod
    def apply(self, *streams, config: Dict) -> DataStream:
        pass

class PipelineBuilderFactory(ABC):
    def __init__(self, pipeline_config, sinksourcemanager, transform_factory):
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

class PipelineConfigImpl:
    def __init__(self):
        self._config_internal = {}
        self._config_pipeline = {}

    @property
    def config_internal(self):
        return self._config_internal

    @config_internal.setter
    def config_internal(self, value):
        self._config_internal = value

    @property
    def config_pipeline(self):
        return self._config_pipeline

    @config_pipeline.setter
    def config_pipeline(self, value):
        self._config_pipeline = value

    def create_default_pipeline_env(self):
        env = StreamExecutionEnvironment.get_execution_environment()
        if "Pipeline" in self._config_pipeline and "Max_Parallelism" in self._config_pipeline["Pipeline"]:
            env.set_max_parallelism(int(self._config_pipeline["Pipeline"]["Max_Parallelism"]))
        for jar in self._config_pipeline.get("JARS", []):
            env.add_jars(f"file:///opt/flink/lib/{jar}")
        return env

class SourceSinkManager:
    def __init__(self, config):
        self.config = config

    def get_sources_info(self) -> List[str]:
        return list(self.config.config_internal["Sources"].keys())

    def get_sources(self, config) -> Dict[str, Any]:
        dict_retrn = {}
        source_config = config.config_internal["Sources"]
        for name, source in source_config.items():
            if source["type"] == "kafka":
                obj = FlinkSourceKafkaImplV2()
                dict_retrn[name] = obj.create_source(config=source)
        return dict_retrn

    def get_sinks_info(self) -> List[str]:
        return list(self.config.config_internal["Sinks"].keys())

    def get_sinks(self, config) -> Dict[str, Any]:
        dict_retrn = {}
        sinks_config = config.config_internal["Sinks"]
        for name, sink in sinks_config.items():
            obj = FlinkSinkImplPostgres()
            dict_retrn[name] = obj.create_sink(config=sink)
        return dict_retrn

class FlinkSourceKafkaImplV2:
    @property
    def source_type(self):
        return "kafka"

    def create_source(self, config: Dict) -> KafkaSource:
        kafka_props = config["config"]
        topic = config["topic_name"]
        group_id = kafka_props.get("group.id", "default_group")
        source_builder = KafkaSource.builder() \
            .set_bootstrap_servers(kafka_props["bootstrap.servers"]) \
            .set_topics(topic) \
            .set_group_id(group_id)

        config_default = {"security.protocol": "PLAINTEXT"}
        config_default.update(kafka_props)
        for key, value in config_default.items():
            source_builder.set_property(key, str(value))

        if "latest_offset" in config and config["latest_offset"]:
            starting_offsets = KafkaOffsetsInitializer.latest()
        else:
            starting_offsets = KafkaOffsetsInitializer.earliest()
        source_builder.set_starting_offsets(starting_offsets)

        deserializer = SimpleStringSchema()
        source_builder.set_value_only_deserializer(deserializer)

        return source_builder.build()

class FlinkSinkImplPostgres:
    @property
    def sink_type(self):
        return "jdbc"

    def create_sink(self, config):
        jdbc_props = config["config"]
        type_info_postgres = Types.ROW(convert_to_flinkdatarow(type_str=str(jdbc_props["types_str"])))
        user_name = jdbc_props['user']
        password = jdbc_props['password']

        jdbc_sink = JdbcSink.sink(
            jdbc_props['sql_statement'], type_info_postgres,
            JdbcConnectionOptions.JdbcConnectionOptionsBuilder().with_url(
                f"{jdbc_props['connectionstring']}/{jdbc_props['database']}").with_driver_name(jdbc_props['driver']).
            with_user_name(user_name).with_password(password).build(),
            JdbcExecutionOptions.builder().with_batch_interval_ms(
                int(jdbc_props['insertbatchinterval'])).with_batch_size(
                int(jdbc_props['batchsize'])).with_max_retries(int(jdbc_props['retries'])).build())

        return jdbc_sink

class ParseKafkaMessge(TransformationAbstract):
    def __json_parse(self, data):
        error_flag = False
        try:
            dict_data = json.loads(data)
            return (dict_data, error_flag, None)
        except Exception as e:
            full_msg = str(e) + "\n" + traceback.format_exc()
            current_time = datetime.datetime.now()
            data_pass = ErrorLogInternalData(data, data, "UC-x", "RAW", str(full_msg), current_time)
            error_flag = True
            return (data, error_flag, [data_pass])

    def apply(self, *streams, config=None) -> DataStream:
        return streams[0].map(lambda x: self.__json_parse(x))

class FilterStreamMain(TransformationAbstract):
    def apply(self, *streams, config=None) -> DataStream:
        return streams[0].filter(lambda x: x[1] == False)

class FilterStreamError(TransformationAbstract):
    def apply(self, *streams, config=None) -> DataStream:
        return streams[0].filter(lambda x: x[1] == True)

class MapErrorDataToFlinkRow(TransformationAbstract):
    def apply(self, *streams, config=None) -> DataStream:
        config_jdbc_dct = config["Sinks"]["JDBCSinkError"]["config"]
        rows = convert_to_flinkdatarow(config_jdbc_dct["types_str"])
        return streams[0].flat_map(lambda x: (item for item in x[2])).map(lambda x: tuple(x)).map(lambda tuple: Row(*tuple), output_type=rows)

class MapDataToFlinkRow(TransformationAbstract):
    def apply(self, *streams, config) -> DataStream:
        config_jdbc_dct = config["config"]
        rows = convert_to_flinkdatarow(config_jdbc_dct["types_str"])
        return streams[0].map(lambda tuple: Row(*tuple), output_type=rows)

class ParamExtractAndCompose(TransformationAbstract):
    def __convert_dict_element_to_str(self, tuple_data):
        return tuple(json.dumps(item) if isinstance(item, dict) else item for item in tuple_data)

    def __convert_to_list_tuple(self, json_section_dct, is_series, usecase_id, extra_params=None):
        param_list = []
        for key, values_dct in json_section_dct.items():
            tple = ""
            if is_series:
                values = (values_dct, None, None)
            else:
                if isinstance(values_dct["value"], str):
                    value = deepcopy(values_dct["value"])
                    values_dct["value"] = None
                    values_dct["value_string"] = value
                else:
                    values_dct["value_string"] = None
                values = (values_dct["unit"], values_dct["value"], values_dct["value_string"], None, None)
            tple = (str(uuid.uuid4()),) + (key,) + values + (usecase_id,)
            if extra_params is None:
                tple = tple + (None, None, None)
            else:
                tple = tple + tuple(extra_params)
            tple_converted = self.__convert_dict_element_to_str(tple)
            param_list.append(tple_converted)
        return param_list

    def __extract_metric_params(self, json_data, sinks_config_dict, config_section, is_series):
        uc_id = sinks_config_dict["USECASE"]["id"]
        param_scalar_parent_key = sinks_config_dict[config_section]["parent_key"]
        try:
            json_section = get_nested_value_from_dict(json_data, *param_scalar_parent_key.split('.'))
            if json_section is None:
                json_section = {}
        except KeyError:
            json_section = {}
        config_extra = deepcopy(sinks_config_dict[config_section])
        del config_extra["parent_key"]
        extra_params = None
        if len(config_extra) > 0:
            extra_params = []
            for key_target in config_extra.keys():
                if "--None--" not in key_target:
                    extra_params.append(get_nested_value_from_dict(json_data, *key_target.split('.')))
                else:
                    extra_params.append(None)
        return self.__convert_to_list_tuple(json_section, is_series, uc_id, extra_params)

    def __extract_meta_param(self, json_data, sinks_config_dict, config_section_meta):
        param_meta_section = sinks_config_dict[config_section_meta]
        def value_convert_and_extract(value):
            if value == "--None--/key":
                reduced_val = "generated_" + str(uuid.uuid4())
            elif value == "--None--/value":
                reduced_val = {}
            else:
                reduced_val = get_nested_value_from_dict(json_data, *value.split('.'))
            if value == "process.recordedAt":
                return get_utcoffset_of_timezone(reduced_val)
            if value in ["process", "part"]:
                dict_val = deepcopy(reduced_val)
                if value == "process":
                    dict_val.pop("parameters", None)
                    dict_val.pop("recordedAt", None)
                elif value == "part":
                    dict_val.pop("program", None)
                    dict_val.pop("station", None)
                return dict_val
            return reduced_val
        gen_expr = (value_convert_and_extract(value) for value in param_meta_section)
        tuple_meta_param = tuple(gen_expr)
        return self.__convert_dict_element_to_str(tuple_meta_param)

    def __compose_data_list(self, scalar_param_list, series_param_list, meta_tuple):
        data_dict = {}
        data_dict["scalar"] = [meta_tuple + tuple_data for tuple_data in scalar_param_list]
        data_dict["series"] = [meta_tuple + tuple_data for tuple_data in series_param_list]
        return data_dict

    def __validation_check(self, data_dict, SCALAR_PARAM_NUM=18, SERIES_PARAM_NUM=14):
        for v in data_dict["scalar"]:
            if len(v) != SCALAR_PARAM_NUM:
                len_num_detected = len(v)
                print(f"Missing SCALAR parameters, expected {SCALAR_PARAM_NUM}, got {len_num_detected}")
        for v in data_dict["series"]:
            if len(v) != SERIES_PARAM_NUM:
                len_num_detected = len(v)
                print(f"Missing SERIES parameters, expected {SERIES_PARAM_NUM}, got {len_num_detected}")
        print(f"Parameter validation passed")
        return True

    def __extract_compose(self, incomming_json_data, config):
        sinks_config_dict = get_config_section(config["TRANSFORMATION"]["sinks_config"])
        meta_params_tuple = self.__extract_meta_param(incomming_json_data, sinks_config_dict, "META_PARAMS")
        scalar_params_list = self.__extract_metric_params(incomming_json_data, sinks_config_dict, "SCALAR_PARAMS", is_series=False)
        series_params_list = self.__extract_metric_params(incomming_json_data, sinks_config_dict, "SERIES_PARAMS", is_series=True)
        data_dict = self.__compose_data_list(scalar_params_list, series_params_list, meta_params_tuple)
        error_flag = self.__validation_check(data_dict)
        return (data_dict, error_flag)

    def apply(self, *streams, config: Dict) -> DataStream:
        return streams[0].map(lambda x: self.__extract_compose(x, config)).filter(lambda x: x[1] == True).map(lambda x: x[0])

class ScalarMetricStreamFiltering(TransformationAbstract):
    def apply(self, *streams, config=None) -> DataStream:
        return streams[0].filter(lambda x: 'scalar' in x).map(lambda x: x['scalar']).flat_map(lambda x: (tuple_data for tuple_data in x))

class SeriesMetricStreamFiltering(TransformationAbstract):
    def apply(self, *streams, config=None) -> DataStream:
        return streams[0].filter(lambda x: 'series' in x).map(lambda x: x['series']).flat_map(lambda x: (tuple_data for tuple_data in x))

class ContainerWiring(containers.DeclarativeContainer):
    nan_string_replace = providers.Factory(NanStringReplacementImpl)
    parse_kafka_message = providers.Factory(ParseKafkaMessge)
    filter_stream_main = providers.Factory(FilterStreamMain)
    filter_stream_error = providers.Factory(FilterStreamError)
    error_flink_datarow = providers.Factory(MapErrorDataToFlinkRow)
    main_flink_datarow = providers.Factory(MapDataToFlinkRow)
    param_extract_compose = providers.Factory(ParamExtractAndCompose)
    scalar_stream_filter = providers.Factory(ScalarMetricStreamFiltering)
    series_stream_filter = providers.Factory(SeriesMetricStreamFiltering)

class TransformationWiringImplV1:
    def __init__(self):
        self.instantiated_transformations = {}

    def create_transformation(self, t_name, *args):
        print(f"Generating transformation: {t_name}")
        t_instance = self.mapper[t_name]()
        return t_instance

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

class NanStringReplacementImpl(TransformationAbstract):
    def apply(self, *streams, config=None) -> DataStream:
        def __nanStrReplace(raw_json_str: str):
            json_str = raw_json_str.replace(": NaN,", ': "NaN",').replace(": NaN", ': "NaN"')
            return json_str
        return streams[0].map(lambda x: __nanStrReplace(x))

class CustomPipeline(PipelineBuilderFactory):
    def __init__(self, config, sinksourcemanager, transform_factory):
        super().__init__(config, sinksourcemanager, transform_factory)

    def build_pipeline(self):
        pipeline_env = self.pipeline_config.create_default_pipeline_env()
        t_env = StreamTableEnvironment.create(pipeline_env, environment_settings=EnvironmentSettings.new_instance().in_streaming_mode().build())

        # Embedded configurations
        self.pipeline_config.config_internal = {
            "Sources": {
                "Forward": {
                    "type": "kafka",
                    "topic_name": "flink-source",
                    "data_format": "text",
                    "latest_offset": True,
                    "source_implementation": "FlinkSourceKafkaImplV2",
                    "bootstrap_servers": "172.17.0.1:9092",
                    "config": {
                        "group.id": "forward-only",
                        "bootstrap.servers": "172.17.0.1:9092"
                    }
                }
            },
            "Sinks": {
                "JDBCSinkError": {
                    "type": "jdbc",
                    "datatype": "error",
                    "sink_implementation": "FlinkSinkImplPostgres",
                    "source": "Forward",
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
                "JDBCForwardScalarSink": {
                    "source": "Forward",
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
                "JDBCForwardSeriesSink": {
                    "source": "Forward",
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
        self.pipeline_config.config_pipeline = {
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

        sources = self.sinksourcemanager.get_sources(config=self.pipeline_config)
        sinks_pipeline = self.sinksourcemanager.get_sinks(config=self.pipeline_config)

        container = ContainerWiring()
        self.transform_factory.map_transformations(container)

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

        print(mapper)

        if not streams:
            raise ValueError("No streams to union")
        stream = streams[0]

        for s in streams[1:]:
            stream = stream.union(s)

        stream_transform = self.chain("nan_str_replacement", stream).\
                           chain("parse_kafka_message", config=self.pipeline_config.config_pipeline).finish_chain()

        stream_main = self.chain("filter_stream_main", stream_transform).finish_chain()
        stream_error = self.chain("filter_stream_error", stream_transform).\
                       chain("error_flink_datarow", config=self.pipeline_config.config_internal).finish_chain()

        stream_error.add_sink(sinks_pipeline["JDBCSinkError"])
        stream_main = stream_main.map(lambda x: x[0])

        for stream_process_id, sinks_stream in mapper.items():
            stream_individual = stream_main.filter(lambda x: x["process"]["id"] == stream_process_id)

            stream_processed = self.chain("param_extract_compose", stream_individual, config=self.pipeline_config.config_pipeline).finish_chain()

            scalar_stream = self.chain("scalar_stream_filter", stream_processed).finish_chain()
            series_stream = self.chain("series_stream_filter", stream_processed).finish_chain()

            if len(sinks_stream) == 0:
                print("No sinks configured for source: ", stream_process_id)
                continue

            try:
                scalar_sink_config = sinks_stream['scalar']['config']
                series_sink_config = sinks_stream['series']['config']

                scalar_stream = self.chain("main_flink_datarow", scalar_stream, config=scalar_sink_config).finish_chain()
                series_stream = self.chain("main_flink_datarow", series_stream, config=series_sink_config).finish_chain()

                stream_sink_map = {
                    "scalar": scalar_stream,
                    "series": series_stream,
                }

                for sink_datatype, stream in stream_sink_map.items():
                    stream.add_sink(sinks_stream[sink_datatype]['sink_obj'])
            except Exception as e:
                print("Failed to attach sinks to source: ", stream_process_id, "error: ", e, "\n Recheck sinks mapping!")

        pipeline_env.execute("Application Mode Pipeline")

def main():
    pipeline_config = PipelineConfigImpl()
    sinksourcemanager = SourceSinkManager(pipeline_config)
    transformations = TransformationWiringImplV1()
    pipeline = CustomPipeline(pipeline_config, sinksourcemanager, transformations)
    pipeline.build_pipeline()

if __name__ == "__main__":
    main()