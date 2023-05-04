import json
import logging
import os

import pytest
from boto3 import Session
from moto import mock_s3
from pydantic import ValidationError

from datahub.ingestion.run.pipeline import Pipeline
from tests.test_helpers import mce_helpers

FROZEN_TIME = "2020-04-14 07:00:00"


@pytest.fixture(scope="module", autouse=True)
def bucket_name():
    return "my-test-bucket"


@pytest.fixture(scope="module", autouse=True)
def s3_client():
    with mock_s3():
        yield Session(
            aws_access_key_id="test",
            aws_secret_access_key="test",
            region_name="us-east-1",
        ).resource("s3")


@pytest.fixture(scope="module", autouse=True)
def s3_populate(pytestconfig, s3_client, bucket_name):
    logging.info("Populating s3 bucket")
    s3_client.create_bucket(Bucket=bucket_name)
    bkt = s3_client.Bucket(bucket_name)
    test_resources_dir = (
        pytestconfig.rootpath / "tests/integration/s3/test_data/local_system/"
    )
    for root, dirs, files in os.walk(test_resources_dir):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, test_resources_dir)
            bkt.upload_file(full_path, rel_path)
    yield


SOURCE_FILES_PATH = "./tests/integration/s3/sources/s3"
source_files = os.listdir(SOURCE_FILES_PATH)


@pytest.mark.parametrize("source_file", source_files)
def test_data_lake_s3_ingest(
    pytestconfig, s3_populate, source_file, tmp_path, mock_time
):
    test_resources_dir = pytestconfig.rootpath / "tests/integration/s3/"

    f = open(os.path.join(SOURCE_FILES_PATH, source_file))
    source = json.load(f)

    config_dict = {
        "source": source,
        "sink": {
            "type": "file",
            "config": {
                "filename": f"{tmp_path}/{source_file}",
            },
        },
        "run_id": source_file,
    }
    pipeline = Pipeline.create(config_dict)
    pipeline.run()
    pipeline.raise_from_status()

    # Verify the output.
    mce_helpers.check_golden_file(
        pytestconfig,
        output_path=f"{tmp_path}/{source_file}",
        golden_path=f"{test_resources_dir}/golden-files/s3/golden_mces_{source_file}",
    )


@pytest.mark.parametrize("source_file", source_files)
def test_data_lake_local_ingest(pytestconfig, source_file, tmp_path, mock_time):
    test_resources_dir = pytestconfig.rootpath / "tests/integration/s3/"

    f = open(os.path.join(SOURCE_FILES_PATH, source_file))
    source = json.load(f)

    source["config"]["path_spec"]["include"] = source["config"]["path_spec"][
        "include"
    ].replace("s3://my-test-bucket/", "tests/integration/s3/test_data/local_system/")
    source["config"]["profiling"]["enabled"] = True
    source["config"].pop("aws_config")
    config_dict = {
        "source": source,
        "sink": {
            "type": "file",
            "config": {
                "filename": f"{tmp_path}/{source_file}",
            },
        },
        "run_id": source_file,
    }
    pipeline = Pipeline.create(config_dict)
    pipeline.run()
    pipeline.raise_from_status()

    # Verify the output.
    mce_helpers.check_golden_file(
        pytestconfig,
        output_path=f"{tmp_path}/{source_file}",
        golden_path=f"{test_resources_dir}/golden-files/local/golden_mces_{source_file}",
    )


def test_data_lake_incorrect_config_raises_error(tmp_path, mock_time):

    # Case 1 : named variable in table name is not present in include
    source = {
        "type": "s3",
        "config": {
            "path_spec": {"include": "a/b/c/d/{table}.*", "table_name": "{table1}"}
        },
    }
    config_dict = {
        "sink": {
            "type": "file",
            "config": {
                "filename": f"{tmp_path}/mces.json",
            },
        },
        "source": source,
    }
    with pytest.raises(ValidationError) as e_info:
        pipeline = Pipeline.create(config_dict)
        pipeline.run()
        pipeline.raise_from_status()

    logging.debug(e_info)

    # Case 2 : named variable in exclude is not allowed
    source = {
        "type": "s3",
        "config": {
            "path_spec": {
                "include": "a/b/c/d/{table}/*.*",
                "exclude": ["a/b/c/d/a-{exclude}/**"],
            }
        },
    }
    config_dict["source"] = source
    with pytest.raises(ValidationError) as e_info:
        pipeline = Pipeline.create(config_dict)
        pipeline.run()
        pipeline.raise_from_status()

    logging.debug(e_info)

    # Case 3 : unsupported file type not allowed
    source = {
        "type": "s3",
        "config": {
            "path_spec": {
                "include": "a/b/c/d/{table}/*.hd5",
            }
        },
    }
    config_dict["source"] = source
    with pytest.raises(ValidationError) as e_info:
        pipeline = Pipeline.create(config_dict)
        pipeline.run()
        pipeline.raise_from_status()

    logging.debug(e_info)

    # Case 4 : ** in include not allowed
    source = {
        "type": "s3",
        "config": {
            "path_spec": {
                "include": "a/b/c/d/**/*.*",
            }
        },
    }
    config_dict["source"] = source
    with pytest.raises(ValidationError) as e_info:
        pipeline = Pipeline.create(config_dict)
        pipeline.run()
        pipeline.raise_from_status()

    logging.debug(e_info)
