import github_actions_tracing


def test_version():
    assert (
        hasattr(github_actions_tracing, "__version__")
        and github_actions_tracing.__version__ is not None
    )
