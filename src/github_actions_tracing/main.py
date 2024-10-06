import json
import re
import time
from datetime import datetime

import requests
from google.protobuf.json_format import MessageToDict
from requests.structures import CaseInsensitiveDict
from watcloud_utils.typer import app

from vendor.generated import perfetto_trace_pb2


def generate_uuid(workflow_run_id, attempt_number=-1, job_id=-1, step_id=-1):
    """
    Generate a unique 64-bit identifier for a given job or step.
    """
    return hash(f"{workflow_run_id}_{attempt_number}_{job_id}_{step_id}") % (2**64)


# Derived from https://github.com/LiluSoft/Sysview-Perfetto-Converter/blob/2d661c5da6513412a9f793bd97e175287d95b246/perfetto_writer.py#L203
def trace_to_json(trace):
    return json.dumps(MessageToDict(trace))


def run_graphql_query(query, token):
    url = "https://api.github.com/graphql"
    headers = CaseInsensitiveDict()
    headers["Authorization"] = f"Bearer {token}"
    headers["Content-Type"] = "application/json"
    response = requests.post(url, headers=headers, json={"query": query})
    response.raise_for_status()
    return response.json()


@app.command()
def get_data(github_url, github_token=None):
    """
    Retrieve data from a GitHub Actions workflow run URL.
    """

    # Extract owner, repo, run_id, and optional attempt number from the URL
    match = re.match(
        r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)(?:/attempts/(?P<attempt>\d+))?",
        github_url,
    )
    if not match:
        raise ValueError("Invalid GitHub Actions URL format")

    owner = match.group("owner")
    repo = match.group("repo")
    run_id = match.group("run_id")
    attempt = match.group("attempt")

    headers = {}

    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    # Retrieve workflow run details
    run_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}"
    if attempt:
        run_url += f"/attempts/{attempt}"
    run_response = requests.get(run_url + "?per_page=100", headers=headers)
    run_response.raise_for_status()

    run_data = run_response.json()
    if not run_data:
        raise ValueError("Failed to retrieve workflow run data.")

    # Retrieve jobs data
    jobs_url = f"{run_url}/jobs"
    jobs_response = requests.get(jobs_url + "?per_page=100", headers=headers)
    jobs_response.raise_for_status()

    jobs_data = jobs_response.json().get("jobs", [])
    if not jobs_data:
        raise ValueError("Failed to retrieve jobs data.")

    return {
        "run": run_data,
        "jobs": jobs_data,
    }


def to_ns(iso):
    """
    Convert an ISO 8601 timestamp to nanoseconds since the Unix epoch.
    """
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").timestamp() * 1e9)


# A trusted packet sequence ID is required to identify the thread that's generating
# the trace events. Since we are not using multiple threads, we set it to an arbitrary
# value.
# Discussion: https://github.com/google/perfetto/issues/124
TRUSTED_PACKET_SEQUENCE_ID = 42


@app.command()
def create_trace_file(
    data=None,
    data_json=None,
    output_file="github_actions.perfetto-trace",
    output_debug_json=None,
):
    """
    Create a Perfetto trace file from the given data.

    References:
    - https://perfetto.dev/docs/reference/synthetic-track-event
    """
    if not data:
        with open(data_json) as f:
            data = json.load(f)

    run_uuid = generate_uuid(data["run"]["id"], data["run"]["run_attempt"])

    trace = perfetto_trace_pb2.Trace()

    workflow_process_descriptor_packet = trace.packet.add()
    # recommended to set this flag to indicate that the state of the sequence is cleared
    # https://github.com/google/perfetto/issues/124
    workflow_process_descriptor_packet.sequence_flags = (
        perfetto_trace_pb2.TracePacket.SequenceFlags.SEQ_INCREMENTAL_STATE_CLEARED
    )
    workflow_process_descriptor_packet.trusted_packet_sequence_id = (
        TRUSTED_PACKET_SEQUENCE_ID
    )
    workflow_process_descriptor_packet.track_descriptor.uuid = run_uuid
    workflow_process_descriptor_packet.track_descriptor.process.pid = data["run"][
        "run_number"
    ]
    workflow_process_descriptor_packet.track_descriptor.process.process_name = f"{data['run']['display_title']} run {data['run']['id']} attempt {data['run']['run_attempt']} - "

    jobs = sorted(data["jobs"], key=lambda job: job["created_at"])

    for job_i, job in enumerate(jobs):
        if job["conclusion"] in ["skipped"]:
            continue

        job_create_ns = to_ns(job["created_at"])
        job_end_ns = to_ns(job["completed_at"])

        # Sometimes the job start time is later than the first step start time.
        # In this case, we need to fix the job start time for visualization purposes.
        first_step = job["steps"][0] if job["steps"] else None
        job_start_ns = min(
            to_ns(job["started_at"]),
            to_ns(first_step["started_at"]) if first_step else to_ns(job["started_at"]),
        )

        job_uuid = generate_uuid(
            data["run"]["id"], data["run"]["run_attempt"], job["id"]
        )
        job_descriptor_packet = trace.packet.add()
        job_descriptor_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
        job_descriptor_packet.track_descriptor.uuid = job_uuid
        job_descriptor_packet.track_descriptor.parent_uuid = run_uuid
        job_descriptor_packet.track_descriptor.thread.pid = (
            workflow_process_descriptor_packet.track_descriptor.process.pid
        )
        job_descriptor_packet.track_descriptor.thread.tid = job_i
        job_descriptor_packet.track_descriptor.thread.thread_name = (
            f"{job['runner_name']} ({job['runner_id']})"
        )

        job_create_packet = trace.packet.add()
        job_create_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
        job_create_packet.timestamp = job_create_ns
        job_create_packet.track_event.track_uuid = job_uuid
        job_create_packet.track_event.type = (
            perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
        )
        job_create_packet.track_event.name = job["name"]
        job_create_packet.track_event.categories.extend(["job", "slice"])

        job_waiting_start_packet = trace.packet.add()
        job_waiting_start_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
        job_waiting_start_packet.timestamp = job_create_ns
        job_waiting_start_packet.track_event.track_uuid = job_uuid
        job_waiting_start_packet.track_event.type = (
            perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
        )
        job_waiting_start_packet.track_event.name = "Waiting for runner"
        job_waiting_start_packet.track_event.categories.extend(["job", "slice"])

        job_waiting_end_packet = trace.packet.add()
        job_waiting_end_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
        job_waiting_end_packet.timestamp = job_start_ns
        job_waiting_end_packet.track_event.track_uuid = job_uuid
        job_waiting_end_packet.track_event.type = (
            perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
        )

        job_running_packet = trace.packet.add()
        job_running_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
        job_running_packet.timestamp = job_start_ns
        job_running_packet.track_event.track_uuid = job_uuid
        job_running_packet.track_event.type = (
            perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
        )
        job_running_packet.track_event.name = "Running"
        job_running_packet.track_event.categories.extend(["job", "instant"])

        for step in job["steps"]:
            step_start_ns = to_ns(step["started_at"])
            step_end_ns = to_ns(step["completed_at"])

            step_start_packet = trace.packet.add()
            step_start_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
            step_start_packet.timestamp = step_start_ns
            step_start_packet.track_event.track_uuid = job_uuid
            step_start_packet.track_event.type = (
                perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
            )
            step_start_packet.track_event.name = step["name"]
            step_start_packet.track_event.categories.extend(["step", "slice"])

            step_end_packet = trace.packet.add()
            step_end_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
            step_end_packet.timestamp = step_end_ns
            step_end_packet.track_event.track_uuid = job_uuid
            step_end_packet.track_event.type = (
                perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
            )

        job_running_end_packet = trace.packet.add()
        job_running_end_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
        job_running_end_packet.timestamp = job_end_ns
        job_running_end_packet.track_event.track_uuid = job_uuid
        job_running_end_packet.track_event.type = (
            perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
        )

        job_end_packet = trace.packet.add()
        job_end_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID
        job_end_packet.timestamp = job_end_ns
        job_end_packet.track_event.track_uuid = job_uuid
        job_end_packet.track_event.type = (
            perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
        )

    # Write the trace to a JSON file for debugging
    if output_debug_json:
        with open(output_debug_json, "w") as f:
            f.write(trace_to_json(trace))

        print(f"Trace Debug JSON written to {output_debug_json}")

    # Write the trace to a binary file
    with open(output_file, "wb") as f:
        f.write(trace.SerializeToString())

    print(
        f"Trace file written to {output_file}. You can view it using the Perfetto UI (https://ui.perfetto.dev/)."
    )


@app.command()
def generate_trace(
    github_url,
    github_token=None,
    output_file="github_actions.perfetto-trace",
    output_debug_json=None,
):
    """
    Generate a Perfetto trace file from a GitHub Actions workflow run URL.
    """

    try:
        print(f"Fething data from {github_url}")
        data = get_data(github_url, github_token)
        print("Creating trace file")
        create_trace_file(
            data=data, output_file=output_file, output_debug_json=output_debug_json
        )
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}")
        raise
    except ValueError as e:
        print(f"Input error: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise


if __name__ == "__main__":
    app()
