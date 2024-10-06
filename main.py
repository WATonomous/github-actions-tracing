import json
import re
import time
from datetime import datetime

import requests
from google.protobuf.json_format import MessageToDict
from requests.structures import CaseInsensitiveDict
from watcloud_utils.typer import app

from vendor import perfetto_trace_pb2

# TODO: switch back to REST. Just need 2 API calls:
# https://api.github.com/repos/{{OWNER}}/{{REPO}}/actions/runs/11196620081/attempts/1
# https://api.github.com/repos/{{OWNER}}/{{REPO}}/actions/runs/11196620081/attempts/1/jobs
# This gives us created_at per job.

def generate_uuid(workflow_run_id, attempt_number = -1, job_id = -1, step_id = -1):
    """
    Generate a unique 64-bit identifier for a given job or step.
    """
    return hash(f"{workflow_run_id}_{attempt_number}_{job_id}_{step_id}") % (2 ** 64)

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
def get_data(url, token):
    # Extract owner, repo, run_id, and optional attempt number from the URL
    match = re.match(
        r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)(?:/attempts/(?P<attempt>\d+))?",
        url,
    )
    if not match:
        raise ValueError("Invalid GitHub Actions URL format")
    
    owner = match.group("owner")
    repo = match.group("repo")
    run_id = match.group("run_id")
    attempt = match.group("attempt")

    headers = {"Authorization": f"token {token}"}

    # Retrieve workflow run details
    run_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}"
    if attempt:
        run_url += f"/attempts/{attempt}"
    run_response = requests.get(run_url, headers=headers)
    run_response.raise_for_status()

    run_data = run_response.json()
    if not run_data:
        raise ValueError("Failed to retrieve workflow run data.")
    
    # Retrieve jobs data
    jobs_url = f"{run_url}/jobs"
    jobs_response = requests.get(jobs_url, headers=headers)
    jobs_response.raise_for_status()

    jobs_data = jobs_response.json().get("jobs", [])
    if not jobs_data:
        raise ValueError("Failed to retrieve jobs data.")
    
    return run_data, jobs_data

# @app.command()
# def get_run_data(url, token):
#     # Extract owner, repo, and run ID from the URL
#     match = re.match(
#         r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)",
#         url,
#     )
#     if not match:
#         raise ValueError("Invalid GitHub Actions URL format")

#     owner = match.group("owner")
#     repo = match.group("repo")
#     run_id = match.group("run_id")

#     headers = {"Authorization": f"token {token}"}

#     # Retrieve workflow run details
#     rest_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}"
#     rest_response = requests.get(rest_url, headers=headers)
#     rest_response.raise_for_status()
#     run_data_rest = rest_response.json()

#     # Retrieve node ID for GraphQL query
#     node_id = run_data_rest.get("node_id")
#     if not node_id:
#         raise ValueError("Failed to retrieve node ID for the workflow run.")

#     # GraphQL query to get additional details using the node ID
#     query = f"""
#     {{
#         node(id: "{node_id}") {{
#             ... on WorkflowRun {{
#                 runNumber
#                 createdAt
#                 event
#                 checkSuite {{
#                     conclusion
#                     createdAt
#                     checkRuns(first: 100) {{
#                         totalCount
#                         nodes {{
#                             id
#                             startedAt
#                             completedAt
#                             name
#                             conclusion
#                             steps(first: 100) {{
#                                 totalCount
#                                 nodes {{
#                                     name
#                                     startedAt
#                                     completedAt
#                                     status
#                                     secondsToCompletion
#                                 }}
#                             }}
#                         }}
#                     }}
#                 }}
#             }}
#         }}
#     }}
#     """
#     graphql_response = run_graphql_query(query, token)
#     run_data = graphql_response.get("data", {}).get("node", {})
#     if not run_data:
#         raise ValueError("Failed to retrieve workflow run data using GraphQL.")

#     return run_data

# A trusted packet sequence ID is required to identify the thread that's generating
# the trace events. Since we are not using multiple threads, we set it to an arbitrary
# value.
# Discussion: https://github.com/google/perfetto/issues/124
TRUSTED_PACKET_SEQUENCE_ID = 42

@app.command()
def create_trace_file(run_data = None, run_data_json = None):
    if not run_data:
        with open(run_data_json) as f:
            run_data = json.load(f)

    created_at = datetime.strptime(run_data["createdAt"], "%Y-%m-%dT%H:%M:%SZ")

    trace = perfetto_trace_pb2.Trace()

    # Create trace packet for workflow run
    # workflow_descriptor_packet = trace.packet.add()
    # workflow_descriptor_packet.sequence_flags = (
    #     perfetto_trace_pb2.TracePacket.SequenceFlags.SEQ_INCREMENTAL_STATE_CLEARED
    # )
    # workflow_descriptor_packet.track_descriptor.uuid = run_data["runNumber"]
    # workflow_descriptor_packet.track_descriptor.name = "Run"
    # workflow_descriptor_packet.track_descriptor.thread.pid = 123
    # workflow_descriptor_packet.track_descriptor.thread.tid = 456

    workflow_start_packet = trace.packet.add()
    workflow_start_packet.timestamp = int(created_at.timestamp() * 1e9)
    workflow_start_packet.track_event.track_uuid = run_data["runNumber"]
    workflow_start_packet.track_event.type = perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
    workflow_start_packet.track_event.name = "Workflow"
    workflow_start_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID

    workflow_end_packet = trace.packet.add()
    workflow_end_packet.timestamp = int((created_at.timestamp() + 20) * 1e9)
    workflow_end_packet.track_event.track_uuid = run_data["runNumber"]
    workflow_end_packet.track_event.type = perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
    workflow_end_packet.trusted_packet_sequence_id = TRUSTED_PACKET_SEQUENCE_ID



    # clock_snapshot = trace.packet.add().clock_snapshot
    # clock = clock_snapshot.clocks.add()
    # clock.clock_id = perfetto_trace_pb2.ClockSnapshot.Clock.BuiltinClocks.MONOTONIC
    # clock.timestamp = int(time.mktime(time.strptime(run_data["createdAt"], "%Y-%m-%dT%H:%M:%SZ")) * 1e6)
    # Create trace packet for workflow run
    # start_time = int(
    #     time.mktime(time.strptime(run_data["createdAt"], "%Y-%m-%dT%H:%M:%SZ")) * 1e6
    # )
    # if jobs_data:
    #     end_time = max(
    #         int(
    #             time.mktime(time.strptime(job["completed_at"], "%Y-%m-%dT%H:%M:%SZ"))
    #             * 1e6
    #         )
    #         for job in jobs_data
    #         if job.get("completed_at")
    #     )
    # else:
    #     end_time = start_time

    # workflow_packet = perfetto_trace_pb2.TracePacket()
    # workflow_packet.track_event.type = (
    #     perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
    # )
    # workflow_packet.track_event.name = run_data.get("name", "N/A")
    # workflow_packet.timestamp = start_time
    # workflow_packet.timestamp_clock_id = (
    #     perfetto_trace_pb2.ClockSnapshot.Clock.BuiltinClocks.MONOTONIC
    # )

    # workflow_packet.track_event.track_uuid = hash(run_data["runNumber"]) % (2**64)
    # trace.packet.extend([workflow_packet])

    # # Add TrackDescriptor for workflow run
    # workflow_descriptor = perfetto_trace_pb2.TracePacket()
    # workflow_descriptor.track_descriptor.uuid = hash(run_data["runNumber"]) % (2**64)
    # workflow_descriptor.track_descriptor.name = run_data.get("name", "N/A")
    # trace.packet.extend([workflow_descriptor])

    # # Add end event for workflow run
    # workflow_end_packet = perfetto_trace_pb2.TracePacket()
    # workflow_end_packet.track_event.type = (
    #     perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
    # )
    # workflow_end_packet.track_event.name = run_data.get("name", "N/A")
    # workflow_end_packet.timestamp = end_time
    # workflow_end_packet.timestamp_clock_id = (
    #     perfetto_trace_pb2.ClockSnapshot.Clock.BuiltinClocks.MONOTONIC
    # )
    # workflow_end_packet.track_event.track_uuid = run_data["id"]
    # trace.packet.extend([workflow_end_packet])

    # # Create trace packets for each job and its steps
    # for job in jobs_data:
    #     job_start_time = int(
    #         time.mktime(time.strptime(job["started_at"], "%Y-%m-%dT%H:%M:%SZ")) * 1e6
    #     )
    #     job_end_time = (
    #         int(
    #             time.mktime(time.strptime(job["completed_at"], "%Y-%m-%dT%H:%M:%SZ"))
    #             * 1e6
    #         )
    #         if job.get("completed_at")
    #         else job_start_time
    #     )
    #     runner_name = job.get("runner_name", "N/A")

    #     job_packet = perfetto_trace_pb2.TracePacket()
    #     job_packet.track_event.type = (
    #         perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
    #     )
    #     job_packet.track_event.name = job.get("name", "N/A")
    #     job_packet.timestamp = job_start_time
    #     job_packet.timestamp_clock_id = (
    #         perfetto_trace_pb2.ClockSnapshot.Clock.BuiltinClocks.MONOTONIC
    #     )

    #     job_packet.track_event.track_uuid = hash(job["id"]) % (2**64)
    #     trace.packet.extend([job_packet])

    #     # Add TrackDescriptor for job
    #     job_descriptor = perfetto_trace_pb2.TracePacket()
    #     job_descriptor.track_descriptor.uuid = hash(job["id"]) % (2**64)
    #     job_descriptor.track_descriptor.parent_uuid = hash(run_data["runNumber"]) % (
    #         2**64
    #     )
    #     job_descriptor.track_descriptor.name = job.get("name", "N/A")
    #     trace.packet.extend([job_descriptor])

    #     # Add end event for job
    #     job_end_packet = perfetto_trace_pb2.TracePacket()
    #     job_end_packet.track_event.type = (
    #         perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
    #     )
    #     job_end_packet.track_event.name = job.get("name", "N/A")
    #     job_end_packet.timestamp = job_end_time
    #     job_end_packet.timestamp_clock_id = (
    #         perfetto_trace_pb2.ClockSnapshot.Clock.BuiltinClocks.MONOTONIC
    #     )
    #     job_end_packet.track_event.track_uuid = hash(job["id"]) % (2**64)

    #     trace.packet.extend([job_end_packet])

    #     # Create trace packets for each step in the job
    #     steps = job.get("steps", [])
    #     for step in steps:
    #         if not step.get("started_at"):
    #             continue
    #         step_start_time = int(
    #             time.mktime(time.strptime(step["started_at"], "%Y-%m-%dT%H:%M:%SZ"))
    #             * 1e6
    #         )
    #         step_end_time = (
    #             int(
    #                 time.mktime(
    #                     time.strptime(step["completed_at"], "%Y-%m-%dT%H:%M:%SZ")
    #                 )
    #                 * 1e6
    #             )
    #             if step.get("completed_at")
    #             else step_start_time
    #         )

    #         step_packet = perfetto_trace_pb2.TracePacket()
    #         step_packet.track_event.type = (
    #             perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_BEGIN
    #         )
    #         step_packet.track_event.name = step.get("name", "N/A")
    #         step_packet.timestamp = step_start_time
    #         step_packet.timestamp_clock_id = (
    #             perfetto_trace_pb2.ClockSnapshot.Clock.BuiltinClocks.MONOTONIC
    #         )

    #         step_packet.track_event.track_uuid = hash(f"{job['id']}_step") % (2**64)

    #         trace.packet.extend([step_packet])

    #         # Add TrackDescriptor for step
    #         step_descriptor = perfetto_trace_pb2.TracePacket()
    #         step_descriptor.track_descriptor.uuid = hash(f"{job['id']}_step") % (2**64)
    #         step_descriptor.track_descriptor.parent_uuid = hash(job["id"]) % (2**64)
    #         step_descriptor.track_descriptor.name = step.get("name", "N/A")
    #         trace.packet.extend([step_descriptor])

    #         # Add end event for step
    #         step_end_packet = perfetto_trace_pb2.TracePacket()
    #         step_end_packet.track_event.type = (
    #             perfetto_trace_pb2.TrackEvent.Type.TYPE_SLICE_END
    #         )
    #         step_end_packet.track_event.name = step.get("name", "N/A")
    #         step_end_packet.timestamp = step_end_time
    #         step_end_packet.timestamp_clock_id = (
    #             perfetto_trace_pb2.ClockSnapshot.Clock.BuiltinClocks.MONOTONIC
    #         )
    #         step_end_packet.track_event.track_uuid = hash(f"{job['id']}_step") % (2**64)

    #         trace.packet.extend([step_end_packet])

    # Write the trace to a binary file
    with open("trace_output_perfetto.pftrace", "wb") as f:
        f.write(trace.SerializeToString())

    with open("trace_output_perfetto.json", "w") as f:
        f.write(trace_to_json(trace))

    print("Trace file created successfully as 'trace_output_perfetto.pftrace and trace_output_perfetto.json'")


@app.command()
def get_trace(github_url, github_token):
    # Check if the URL contains an attempt number and raise an error if it does
    if re.search(r"/attempts/\d+", github_url):
        raise ValueError(
            "Only the latest attempt is supported. Please provide a URL without an attempt number."
        )

    try:
        run_data = get_run_data(github_url, github_token)
        create_trace_file(run_data)
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
