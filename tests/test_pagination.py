from unittest.mock import Mock

import github_actions_tracing.main as tracing


def make_response(json_data, links=None):
    response = Mock()
    response.json.return_value = json_data
    response.links = links or {}
    return response


def test_get_data_collects_jobs_from_all_pages(monkeypatch):
    first_jobs_url = (
        "https://api.github.com/repos/octocat/demo/actions/runs/123/"
        "jobs?per_page=100"
    )
    second_jobs_url = first_jobs_url + "&page=2"

    run_response = make_response(
        {
            "head_sha": "abc123",
            "path": ".github/workflows/ci.yml",
        }
    )
    first_jobs_response = make_response(
        {"jobs": [{"id": 1, "name": "first-job"}]},
        {"next": {"url": second_jobs_url}},
    )
    second_jobs_response = make_response(
        {"jobs": [{"id": 2, "name": "second-job"}]}
    )
    content_response = make_response({})

    mock_get = Mock(
        side_effect=[
            run_response,
            first_jobs_response,
            second_jobs_response,
            content_response,
        ]
    )
    monkeypatch.setattr(tracing.requests, "get", mock_get)

    result = tracing.get_data(
        "https://github.com/octocat/demo/actions/runs/123"
    )

    assert [job["name"] for job in result["jobs"]] == [
        "first-job",
        "second-job",
    ]