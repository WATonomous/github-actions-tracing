#!/bin/bash

set -o errexit -o nounset -o pipefail

mkdir -p tmp

check_proto() {
    echo "cf1ec0ad32d6772a2bf852e17195e1616062c2afa2320a2eb3f8af7f7956d7e3 tmp/perfetto_trace.proto" | sha256sum --check $@
}

if ! check_proto --status 2>/dev/null; then
    echo "Downloading and generating python bindings from perfetto_trace.proto"
    # Download the proto file
    wget --no-verbose https://raw.githubusercontent.com/google/perfetto/993ddf5c3382546f1bf7437bb71a087e530e2900/protos/perfetto/trace/perfetto_trace.proto -O tmp/perfetto_trace.proto

    check_proto --quiet

    # Generate python code from proto
    docker run --rm -v $(pwd):/ws -w /ws rvolosatovs/protoc --proto_path=/ws/tmp --python_out=/ws/vendor/generated 'perfetto_trace.proto'
fi

