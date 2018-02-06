from ._exceptions import LoadError, LoadErrorReason


# convert_structure(target_version, data, converters):
#
# Convert a versioned structure if needed.
#
# Args
#   target_version (int): The version of the structure the `converter` outputs
#   data (dict): The data to be handled by this `VersionedStructure`
#   converters [((dict) -> dict)]: An array of function that takes a structure
#   at version `index-1` and outputs the same structure converted to
#   version `index` where `index` is the index where the conversion function is
#   stored in the `converters` array.
#
# Returns:
#   (any, bool): a tuple containing the converted data as a first argument and
#   whether some conversion has been performed (ie: one may want to save the
#   converted data)
#
# Raises:
#   (LoadError): If the conversion cannot be performed for any reason. The
#   actual issue is indicating by the `reason` attribute.
#
# This function provides a mechanism to handle file whose format vary from
# version to version.  It is able to detect whether the file version is correct
# and perform automatic update if needed.
#
# **Example : Working with version 2 and performing automatic conversion from version 1**
#
# Let `data` be the data whose format is the versioned structure we are
# managing. First of all, we declare which version we manage and the converter
# we are using to convert from version 1 to version 2.
#
# ..code::python
#   TARGET_VERSION = 2
#
#   def convert_v1_to_v2(v1_version):
#       v2_version = copy.deepcopy(v1_version)
#       # perform some conversion work
#       return v2_version
#
#   converters = {
#       TARGET_VERSION: convert_v1_to_v2
#   }
# ..
#
# Then, we call `convert_structure` that will perform the conversion if needed.
#
# ..code::python
#   (converted_data, save_needed) = convert_structure(TARGET_VERSION, data, converters)
# ..
#
# Finally, we can save the data if needed:
#
# ..code::python
#   if save_needed:
#       save_yaml(converted_data)
# ..
#
# **Version detection**
#
# This function expect a `version` key to be present in the root of the
# specified data, indicating what is current version of the data. This field
# must be a positive integer or 0.
#
def convert_structure(target_version, data, converters):
    if "version" not in data:
        raise LoadError(LoadErrorReason.NO_FORMAT_VERSION,
                        "Cannot determine the version of the structure")

    if not isinstance(data["version"], int):
        raise LoadError(LoadErrorReason.INVALID_DATA, "The version is not a number")

    if data["version"] > target_version:
        raise LoadError(LoadErrorReason.FORMAT_VERSION_NOT_SUPPORTED,
                        "The version {} is not supported by this version of BuildStream."
                        "The last supported version is {}"
                        .format(data["version"], target_version))

    data_converted = False
    converted_data = data
    for version in range(data["version"], target_version, 1):
        if (version + 1) in converters:
            converter = converters[version + 1]
            converted_data = converter(converted_data)
            converted_data["version"] = version + 1
            data_converted = True
        else:
            raise LoadError(LoadErrorReason.FORMAT_VERSION_NOT_SUPPORTED,
                            "No conversion from version {} to version {}".format(version, version + 1))

    return converted_data, data_converted
