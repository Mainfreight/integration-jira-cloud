
## Develop

`pip install -e .`

## Upload package

```shell
# Install dependencies
python3 -m pip install --user --upgrade setuptools wheel twine

# Build package (remember to clean dist first!)
python3 setup.py sdist bdist_wheel

# Upload to test
python3 -m twine upload --repository-url https://test.pypi.org/legacy/ dist/*

# Upload to PyPI
python3 -m twine upload dist/*
```

## Differences from standards

New cli: `tenable-csv-to-jira`

```sh
Usage: tenable-csv-to-jira [OPTIONS] SCANNAME [CONFIGFILE]

Options:
  --download-path TEXT      [default: /tmp]
  --application-name TEXT   Tag tasks with a specific application
  --setup-only              Performs setup tasks and generates a config file.
  --troubleshoot            Outputs some basic troubleshooting data to file as an
                            issue.
  --ingest-only             Assume scan is already downloaded.
```