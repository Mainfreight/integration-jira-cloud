
## Develop

`pip install -e .`

## Upload package

    python3 -m pip install --user --upgrade twine
    python3 -m pip install --user --upgrade setuptools wheel
    python3 setup.py sdist bdist_wheel

    # Upload to test
    python3 -m twine upload --repository-url https://test.pypi.org/legacy/ dist/*

    # Upload to PyPI
    python3 -m twine upload dist/*