import os
import re
import requests
import json
import argparse
import time
from urllib.parse import urlparse


def retrieve_run_data(url, token):
    # Extract owner, repo, run ID, and attempt from the URL
    match = re.match(
        r"https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)/attempts/(?P<attempt>\d+)",
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
    run_response = requests.get(run_url, headers=headers)
    run_response.raise_for_status()
    run_data = run_response.json()
    run_data["attempt"] = attempt  # Add attempt information to run_data

    return owner, repo, run_data


def retrieve_jobs(owner, repo, run_id, attempt, token):
    headers = {"Authorization": f"token {token}"}
    jobs_url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"
    jobs_data = []
    page = 1
    per_page = 100  # Maximize page size to reduce the number of requests

    while True:
        paginated_jobs_url = f"{jobs_url}?page={page}&per_page={per_page}"
        jobs_response = requests.get(paginated_jobs_url, headers=headers)
        jobs_response.raise_for_status()
        jobs_page_data = jobs_response.json().get("jobs", [])
        if not jobs_page_data:
            break
        jobs_data.extend(jobs_page_data)
        page += 1

    return jobs_data


def create_trace_file(owner, repo, run_data, jobs_data):
    trace_data = {"traceEvents": []}

    # Create trace event for workflow run
    start_time = int(
        time.mktime(time.strptime(run_data["created_at"], "%Y-%m-%dT%H:%M:%SZ")) * 1e6
    )
    if jobs_data:
        end_time = max(
            int(
                time.mktime(time.strptime(job["completed_at"], "%Y-%m-%dT%H:%M:%SZ"))
                * 1e6
            )
            for job in jobs_data
            if job.get("completed_at")
        )
    else:
        end_time = start_time
    trace_data["traceEvents"].append(
        {
            "name": run_data.get("name", "N/A"),
            "ph": "X",
            "ts": start_time,
            "dur": end_time - start_time,
            "pid": run_data["id"],
            "tid": "workflow",
            "args": {
                "repo": f"{owner}/{repo}",
                "status": run_data.get("status", "N/A"),
            },
        }
    )

    # Create trace events for each job
    for job in jobs_data:
        job_start_time = int(
            time.mktime(time.strptime(job["started_at"], "%Y-%m-%dT%H:%M:%SZ")) * 1e6
        )
        job_end_time = (
            int(
                time.mktime(time.strptime(job["completed_at"], "%Y-%m-%dT%H:%M:%SZ"))
                * 1e6
            )
            if job.get("completed_at")
            else job_start_time
        )
        runner_name = job.get("runner_name", "N/A")
        trace_data["traceEvents"].append(
            {
                "name": job.get("name", "N/A"),
                "ph": "X",
                "ts": job_start_time,
                "dur": job_end_time - job_start_time,
                "pid": run_data["id"],
                "tid": runner_name if runner_name != "N/A" else f"job_{job['id']}",
                "args": {
                    "status": job.get("status", "N/A"),
                    "runner_name": runner_name,
                },
            }
        )

    with open("trace_output_perfetto.json", "w") as f:
        json.dump(trace_data, f, indent=4)


def main():
    parser = argparse.ArgumentParser(
        description="Generate trace file for a GitHub Actions run."
    )
    parser.add_argument("--url", required=True, help="The GitHub Actions run URL.")
    parser.add_argument("--token", required=True, help="GitHub token for API access.")
    args = parser.parse_args()

    github_url = args.url.strip()
    github_token = args.token.strip()

    try:
        owner, repo, run_data = retrieve_run_data(github_url, github_token)
        jobs_data = retrieve_jobs(
            owner, repo, run_data["id"], run_data["attempt"], github_token
        )
        create_trace_file(owner, repo, run_data, jobs_data)
        print("Trace file created successfully as 'trace_output_perfetto.json'.")
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}")
    except ValueError as e:
        print(f"Input error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
