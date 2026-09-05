# Releasing funcviz

This project publishes to PyPI with a hatchling build and GitHub Actions
Trusted Publishing (OIDC) — no long-lived API token is stored in the repo.

## One-time setup

On PyPI, add a **pending publisher** for the `funcviz` project pointing at this
repository, workflow file `release.yml`, and environment `pypi`. This authorizes
the workflow to publish without a token.

## Cutting a release

1. Bump `version` in `pyproject.toml` and add a matching section to
   `CHANGELOG.md`.
2. Merge to `main`.
3. Tag and push:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. Create a GitHub Release from the tag. Publishing the release triggers
   `.github/workflows/release.yml`, which builds the sdist + wheel and uploads
   them to PyPI via Trusted Publishing.

## Verifying a build locally before tagging

```bash
python -m build
python -m twine check dist/*

# clean-machine simulation (no PYTHONPATH, no editable install)
python -m venv /tmp/fvclean
/tmp/fvclean/bin/pip install dist/funcviz-*.whl
/tmp/fvclean/bin/funcviz --help
cp traces/success.json /tmp/fvclean/success.json
cd /tmp/fvclean && ./bin/funcviz view success.json --html-out out.html
```

Assert that both artifacts contain `funcviz/viewer/index.html`, `twine check`
passes, and `funcviz view` renders a trace against a user-supplied file.
