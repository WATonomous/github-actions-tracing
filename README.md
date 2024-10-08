# github-actions-tracing

A tool for generating traces from GitHub Actions.
The generated traces are compatible with [Perfetto](https://ui.perfetto.dev/).
Example traces can be found in this [discussion post](https://github.com/WATonomous/github-actions-tracing/discussions/13).

## Getting started

1. Download the `.whl` file from the [latest release](https://github.com/WATonomous/github-actions-tracing/releases/latest).
2. Install the wheel: `pip install <path_to_file.whl>`
3. Run the CLI: `gatrace --help`

Example usage:

```bash
gatrace generate-trace https://github.com/WATonomous/github-actions-tracing/actions/runs/11205960644
```

This will generate a trace file in the current directory.

To view the trace, you can use [Perfetto UI](https://ui.perfetto.dev/).

To generate traces for private repositories, you will need to provide a GitHub token. You can do this by passing the `--github-token` argument to the CLI.

```bash
gatrace generate-trace <run_url> --github-token <token>
```

Note that to view organization private repositories, the token must have the [`read:org` scope](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#types-of-personal-access-tokens).

## Development

This project uses [PDM](https://pdm-project.org/) for dependency management.

```bash
# Install dependencies
pdm sync --dev

# Run tests
pdm run --verbose pytest tests

# Run CLI
pdm run gatrace
```

## Releasing

Releases are manually created from the [Releases page](https://github.com/WATonomous/github-actions-tracing/releases).
CI will automatically build the wheel and publish it to the release page.
Release notes can be auto-generated via the web interface.

Please follow [semantic versioning](https://semver.org/) when creating tags for releases.
Tags should be prefixed with `v` (e.g. `v1.0.0`).
Version numbers less than `1.0.0` should be considered unstable and may have breaking changes in minor versions.
