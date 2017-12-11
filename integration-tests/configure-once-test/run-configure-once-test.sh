#!/bin/bash
#
# This test executes a scenario as follows:
# - Open a workspace for the element "target.bst"
# - Build "target.bst"
# - Checkout artifacts
# - Modify workspace by creating a new file in it
# - Build "target.bst"
# - Checkout artifacts
#
# Finally, artifacts from both build runs are compared to determine if build has
# been done twice, but configure step has been done only once.

set -eu
source ../lib.sh

# run_test
#
# Run tests for this test case.
#
run_test () {
	local success=0
	local element_name="target.bst"

	bst_with_flags workspace open ${element_name} "target_workspace"
	bst_with_flags build ${element_name}
	bst_with_flags checkout ${element_name} "target_output"

	build_timestamp_1=$(cat target_output/build_timestamp)
	configure_timestamp_1=$(cat target_output/configure_timestamp)

	sleep 2

	date > target_workspace/a_new_file

	bst_with_flags build ${element_name}
	bst_with_flags checkout ${element_name} "target_output2"

	build_timestamp_2=$(cat target_output2/build_timestamp)
	if [ -r target_output2/configure_timestamp ]; then
		configure_timestamp_2=$(cat target_output2/configure_timestamp)
	else
	#
		configure_timestamp_2=${configure_timestamp_1}
	fi

	if [ "$build_timestamp_1" == "$build_timestamp_2" ]; then
		printf "Build timestamps are ${RED}same${END}, bad!\n"
		success=1
	else
		printf "Build timestamps are ${GREEN}different${END}, good!\n"
	fi

	if [ "$configure_timestamp_1" == "$configure_timestamp_2" ]; then
		printf "Configure timestamps are ${GREEN}same${END}, good!\n"
	else
		printf "Configure timestamps are ${RED}different${END}, bad!\n"
		success=1
	fi

	report_results "configure-once-test" "$success"

	return $success
}

run_test "$@"
