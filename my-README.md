
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