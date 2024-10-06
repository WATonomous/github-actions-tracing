# github-actions-tracing

A tool for generating traces from GitHub Actions. The generated traces are compatible with [Perfetto](https://ui.perfetto.dev/).

## Getting started

1. Download the `.whl` file from the [latest release](https://github.com/WATonomous/github-actions-tracing/releases/latest).
2. Install the wheel: `pip install <path_to_file.whl>`
3. Run the CLI: `gatrace`

## Development

```bash
# Install dependencies
pdm sync --dev

# Run tests
pdm run --verbose pytest tests

# Run CLI
pdm run gatrace
```

