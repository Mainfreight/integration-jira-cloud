#!/usr/bin/env python
"""
MIT License

Copyright (c) 2019 Tenable Network Security, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import click
import logging
import time
import yaml
import json
import platform
import sys
from tenable.io import TenableIO
from tenable.sc import TenableSC
from .config import base_config
from restfly.utils import dict_merge
from .jira import Jira
from .transform import Tio2Jira
from . import __version__
import csv
import os
import arrow
import re
from .scan_downloader import ScanDownloader

# Regex to pull out the vulnerable URL from the Plugin Output
# detected\son\s([\w:\/\.-]+)
AFFECTED_URL_RE = re.compile(
    r"""
    (?:detected\son\s([\w:\/\.-]+))
    |
    (?:URL\n-----\n(.+)\n)
    |
    (?:URL:\s?([\w:\/\.-]+))
    """,
    re.VERBOSE,
)

troubleshooting = """
### Configuration File:
```yaml
{configfile}
```

### Debug Logs
```
{logging}
```

### Available IssueTypes
```yaml
{issuetypes}
```
"""


@click.command()
@click.option("--download-path", default="/tmp", show_default=True)
@click.argument("scanname")
@click.option(
    "--setup-only",
    is_flag=True,
    help="Performs setup tasks and generates a config file.",
)
@click.option(
    "--troubleshoot",
    is_flag=True,
    help="Outputs some basic troubleshooting data to file as an issue.",
)
@click.option("--ingest-only", is_flag=True, help="Assume scan is already downloaded.")
@click.argument("configfile", default="config.yaml", type=click.File("r"))
def cli(
    scanname,
    download_path,
    configfile,
    setup_only=False,
    troubleshoot=False,
    ingest_only=False,
):
    """
    Tenable.io -> Jira Cloud Transformer & Ingester
    """
    config_from_file = yaml.load(configfile, Loader=yaml.Loader)
    config = dict_merge(base_config(), config_from_file)

    # Get the logging definition and define any defaults as need be.
    log = config.get("log", {})
    log_lvls = {"debug": 10, "info": 20, "warn": 30, "error": 40}
    log["level"] = log_lvls[log.get("level", "warn")]
    log["format"] = log.get(
        "format", "%(asctime)-15s %(name)s %(levelname)s %(message)s"
    )

    # Configure the root logging facility
    if troubleshoot:
        logging.basicConfig(
            level=logging.DEBUG, format=log["format"], filename="tenable_debug.log"
        )
    else:
        logging.basicConfig(**log)

    # Output some basic information detailing the config file used and the
    # python version & system arch.
    logging.info("Tenable2JiraCloud Version {}".format(__version__))
    logging.info("Using configuration file {}".format(configfile.name))
    uname = platform.uname()
    logging.info(
        "Running on Python {} {}/{}".format(
            ".".join([str(i) for i in sys.version_info][0:3]), uname[0], uname[-2]
        )
    )

    # instantiate the Jira object
    jira = get_jira_connection(config)

    # Initiate the Tenable.io API model, the Ingester model, and start the
    # ingestion and data transformation.
    if (
        config["tenable"].get("platform") == "tenable.io"
        or config["tenable"].get("platform") == "csv"
    ):
        source = get_tenable_io_connection(config)
    elif config["tenable"].get("platform") == "tenable.sc":
        source = get_tenable_sc_connection(config)
    else:
        logging.error("No valid Tenable platform configuration defined.")
        exit(1)

    logging.info("Preparing Jira")
    ingest = Tio2Jira(source, jira, config)

    if troubleshoot:
        # if the troubleshooting flag is set, then we will be collecting some
        # basic information and outputting it to the screen in a format that
        # Github issues would expect to format it all pretty.  This should help
        # reduce the amount of time that is spent with back-and-forth debugging.
        try:
            download_and_ingest(
                source, scanname, download_path, config, ingest, ingest_only
            )
        except:
            logging.exception("Caught the following Exception")

        # Some basic redaction of sensitive data, such as API Keys, Usernames,
        # Passwords, and hostnames.
        addr, sc_addr = redact_sensitive_data(config_from_file)

        output = troubleshooting.format(
            configfile=yaml.dump(config_from_file, default_flow_style=False),
            logging=open("tenable_debug.log")
            .read()
            .replace(addr, "<JIRA_CLOUD_HOST>")
            .replace(sc_addr, "<TENABLE_SC_HOST>"),
            issuetypes="\n".join(
                [
                    "{id}: {name}".format(**a)
                    for a in jira.issue_types.list()
                    if a.get("name").lower() in ["task", "subtask", "sub-task"]
                ]
            ),
        )
        print(output)
        print_redaction_notice()
        with open("issue_debug.md", "w") as reportfile:
            print(output, file=reportfile)
        os.remove("tenable_debug.log")
    elif not setup_only:
        download_and_ingest(
            source, scanname, download_path, config, ingest, ingest_only
        )
    elif setup_only:
        # In setup-only mode, the ingest will not run, and instead a config file
        # will be generated that will have all of the JIRA identifiers baked in
        # and will also inform the integration to ignore the screen builder.
        # When using this config, if there are any changes to the code, then
        # this config will need to be re-generated.
        config["screen"]["no_create"] = True
        logging.info("Set to setup-only.  Will not run ingest.")
        logging.info("The following is the updated config file from the setup.")
        with open("generated_config.yaml", "w") as outfile:
            outfile.write(yaml.dump(config, Dumper=yaml.Dumper))
        logging.info('Generated "generated_config.yaml" config file.')
        logging.info(
            "This config file should be updated for every new version of this integration."
        )


def get_jira_connection(config):
    return Jira(
        "https://{}/rest/api/3".format(config["jira"]["address"]),
        config["jira"]["api_username"],
        config["jira"]["api_token"],
    )


def download_and_ingest(source, scanname, download_path, config, ingest, ingest_only):
    logging.info("Proceeding to ingest")
    downloader = ScanDownloader(source)

    if not ingest_only:
        logging.info("Getting latest scan")
        latest_scans = downloader.get_latest_scans(scanname)

        logging.info("Downloading scans")
        downloader.download_scans(
            latest_scans,
            download_path,
            ("severity", "eq", "Critical"),
            ("severity", "eq", "High"),
            format="csv",
            filter_type="or",
        )
        logging.info("Reading scans")
        for scan, hist in latest_scans:
            f = downloader.scan_file_path(download_path, scan, hist)
            logging.info("Opening to read: {}".format(f))
            with open(f, "r") as scanfile:
                ingest_csv_file(scanfile, config, ingest)
    else:
        logging.info("Skipping scan download, assuming we have scan already.")
        logging.info("Reading scans")
        f = os.path.join(download_path, "{}.csv".format(scanname))
        logging.info("Opening to read: {}".format(f))
        num_lines = sum(1 for line in open(f))
        logging.info("Number of lines: {}".format(num_lines))
        with open(f, "r") as scanfile:
            ingest_csv_file(scanfile, config, ingest)


def get_tenable_sc_connection(config):
    return TenableSC(
        config["tenable"].get("address"),
        port=int(config["tenable"].get("port", 443)),
        username=config["tenable"].get("username"),
        password=config["tenable"].get("password"),
        access_key=config["tenable"].get("access_key"),
        secret_key=config["tenable"].get("secret_key"),
        vendor="Tenable",
        product="JiraCloud",
        build=__version__,
    )


def get_tenable_io_connection(config):
    return TenableIO(
        access_key=config["tenable"].get("access_key"),
        secret_key=config["tenable"].get("secret_key"),
        vendor="Tenable",
        product="JiraCloud",
        build=__version__,
    )


def ingest_csv_file(scanfile, config, ingest):
    my_src = csv.DictReader(scanfile, delimiter=",", quotechar='"')
    sevs = [sev.title() for sev in config["tenable"]["tio_severities"]]
    hi_source = [r for r in my_src if r["Risk"] in sevs]
    logging.info("Found {} filtered items".format(len(hi_source)))
    for row in hi_source:
        ingest_csv_row(row, ingest)


def redact_sensitive_data(config_from_file):
    # Some basic redaction of sensitive data, such as API Keys, Usernames,
    # Passwords, and hostnames.
    addr = config_from_file["jira"]["address"]
    sc_addr = "NOTHING_TO_SEE_HERE_AT_ALL"
    config_from_file["jira"]["address"] = "<REDACTED>"
    config_from_file["jira"]["api_token"] = "<REDACTED>"
    config_from_file["jira"]["api_username"] = "<REDACTED>"
    config_from_file["project"]["leadAccountId"] = "<REDACTED>"
    if config_from_file["tenable"].get("address"):
        sc_addr = config_from_file["tenable"]["address"]
        config_from_file["tenable"]["address"] = "<REDACTED>"
    if config_from_file["tenable"].get("access_key"):
        config_from_file["tenable"]["access_key"] = "<REDACTED>"
    if config_from_file["tenable"].get("secret_key"):
        config_from_file["tenable"]["secret_key"] = "<REDACTED>"
    if config_from_file["tenable"].get("username"):
        config_from_file["tenable"]["username"] = "<REDACTED>"
    if config_from_file["tenable"].get("password"):
        config_from_file["tenable"]["password"] = "<REDACTED>"
    return addr, sc_addr


def print_redaction_notice():
    print(
        "\n".join(
            [
                "/-------------------------------NOTICE-----------------------------------\\",
                "| The output above is helpful for us to troubleshoot exactly what is     |",
                "| happening within the code and offer a diagnosis for how to correct.    |",
                "| Please note that while some basic redaction has already been performed |",
                "| that we ask you to review the information you're about to send and     |",
                "| ensure that nothing deemed sensitive is transmitted.                   |",
                "| ---------------------------------------------------------------------- |",
                '| -- Copy of output saved to "issue_debug.md"                            |',
                "\\------------------------------------------------------------------------/",
            ]
        )
    )


def ingest_csv_row(row, ingest):
    logging.info("processing row: {} - {}".format(row["Plugin ID"], row["Name"]))

    # Pull out the URL from the plugin output
    set_url_if_regex_match(row)
    set_subtask_summary(row, row["URL"])
    ingest._process_open_vuln(row, "csv_field")


def set_url_if_regex_match(row):
    # Pull out the URL from the plugin output
    url_match = AFFECTED_URL_RE.search(row["Plugin Output"])

    if url_match:
        # Add a `URL` field to the issue (maps to Affected URL)
        # Picks first non-None in tuple returned from `groups()`
        row["URL"] = next((item for item in url_match.groups() if item is not None), "")
        logging.info("Affected URL: {}".format(row["URL"]))
    else:
        logging.info("No URL found")
        row["URL"] = ""


def set_subtask_summary(row, url):
    """
    url parameter enforces sequential processing.
    """
    rawSummary = "[{}] {}: {}".format(row["Plugin ID"], row["Name"], url)
    # Summary can only take 255 characters and URLs may blow this out.
    row["SubtaskSummary"] = rawSummary[:253] + (rawSummary[253:] and "..")
    logging.info("Subtask summary: {}".format(row["SubtaskSummary"]))
