# Clotho

## Project description

Clotho is a personal knowledge organization project. It attempts to provide a seamless
way to organize a large collection of markdown notes. Techniques possible covered are:

- topic modeling
- keyword extraction
- scraping
- semantic search
- knowledge graphs
- embeddings

## Tech Stack

**Python:** 3.13  
**Tools:** UV (packages), Ruff (lint/format), Ty (type check)

## Commands

### UV Package Management

```bash
uv add <package>           # Add dependency
uv add --dev <package>     # Add dev dependency
uv run ruff check .        # Lint
uv run ruff format .       # Format code
```

### Helix CLI

```bash
helix check       # Validate config and queries
helix compile     # Compile queries to executable
helix build       # Build instance
helix push        # Deploy/update instance
helix start       # Start stopped instance
helix stop        # Stop instance
helix status      # Show instance status
helix prune       # Clean unused containers
```

## Code Standards

✅ **Always do:**

- Type hint all function parameters and return types. Prefer builtin types (e.g. `list`, `dict`) over `typing` module
  types (e.g. `List`, `Dict`).
- Raise specific exceptions with context
- When writing regex, put the pattern inside a constant with the _RE suffix for the variable name (e.g. `DATE_RE`).
- When adding imports in a __init__.py file, add it to the `__all__` list as well. 
- If you're importing a variable or function from another file in the same module, use a relative import.

⚠️ **Ask first:**

- Adding dependencies beyond core stack
- Changing schema node/edge types
- Modifying query patterns
- Processing strategy changes

🚫 **Never do:**

- Skip type hints on functions
- Hardcode file paths
- Use lazy imports inside of functions