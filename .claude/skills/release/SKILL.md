---
name: release
description: Create a new release with git tag and push to GitHub. Fetches latest version and creates next patch version by default.
allowed-tools: Bash(git *) Bash(gh *) Read
---

# Release Version Management

This skill automates the release workflow for bedrock-observability.

## Usage

Create a new release tag and push to GitHub:

```
/release
```

Create a specific version:

```
/release 0.0.1
```

## What it does

1. **Fetches the latest version** from GitHub releases
2. **Calculates next version** (increments patch version by default)
3. **Creates annotated git tag** with release message
4. **Pushes tag** to GitHub, triggering the automated release workflow

## Workflow

- Gets latest tag from GitHub: `gh release list --limit 1`
- Creates new tag: `git tag -a v{VERSION} -m "Release {VERSION}"`
- Pushes tags: `git push --tags`

This integrates with the release.yaml workflow which automatically:
- Packages the source code
- Creates a GitHub Release