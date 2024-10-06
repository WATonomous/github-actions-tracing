# github-actions-tracing

A tool for generating traces from GitHub Actions. The generated traces are compatible with [Perfetto](https://ui.perfetto.dev/).

## Getting started

```bash
# Install dependencies
pdm install

# Run tests
pdm run --verbose pytest tests

# Run CLI
pdm run gatrace
```

