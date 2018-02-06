from buildstream._versionedstructure import convert_structure
from buildstream._loader import LoadError, LoadErrorReason

import pytest
import copy


def test_identity_behavior():
    TARGET_VERSION = 1
    data = {
        "version": TARGET_VERSION,
        "data_v1": "Hello"
    }

    (converted_data, save_needed) = convert_structure(TARGET_VERSION, data, [])
    assert converted_data["version"] == TARGET_VERSION, "The version number has been modified"
    assert converted_data["data_v1"] == "Hello", "The data has been changed"
    assert not save_needed


def test_version_not_found():
    TARGET_VERSION = 1
    data = {
        "foo": "bar"
    }

    with pytest.raises(LoadError) as e:
        (_, _) = convert_structure(TARGET_VERSION, data, [])

    assert e.value.reason == LoadErrorReason.NO_FORMAT_VERSION


def test_version_supported():
    TARGET_VERSION = 1
    data = {
        "foo": "bar",
        "version": 2
    }

    with pytest.raises(LoadError) as e:
        (_, _) = convert_structure(TARGET_VERSION, data, [])

    assert e.value.reason == LoadErrorReason.FORMAT_VERSION_NOT_SUPPORTED


def test_version_not_supported_no_conversion():
    TARGET_VERSION = 3

    def converter_2_to_3(old_data):
        return old_data

    converters = {
        3: converter_2_to_3
    }

    data = {
        "foo": "bar",
        "version": 2
    }

    (converted_data, save_needed) = convert_structure(TARGET_VERSION, data, converters)

    assert converted_data["foo"] == data["foo"]
    assert converted_data["version"] == 3
    assert save_needed

    data = {
        "foo": "bar",
        "version": 1
    }

    with pytest.raises(LoadError) as e:
        (converted_data, save_needed) = convert_structure(TARGET_VERSION, data, converters)

    assert e.value.reason == LoadErrorReason.FORMAT_VERSION_NOT_SUPPORTED


def test_converter_called():
    TARGET_VERSION = 2

    data = {
        "version": 1,
        "data_v1": "Hello"
    }

    def converter_1_to_2(old_data):
        converted_data = copy.deepcopy(old_data)
        converted_data["version"] = 2
        converted_data["data_v2"] = "World"
        return converted_data

    converters = {
        2: converter_1_to_2
    }

    (converted_data, save_needed) = convert_structure(TARGET_VERSION, data, converters)
    assert converted_data["version"] == 2, "The version number has not been updated"
    assert converted_data["data_v2"] == "World", "The new field has not beed added"
    assert save_needed


def test_version_is_number():
    TARGET_VERSION = 1

    data = {
        "version": "alpha"
    }

    with pytest.raises(LoadError) as e:
        (_, _) = convert_structure(TARGET_VERSION, data, [])

    assert e.value.reason == LoadErrorReason.INVALID_DATA
