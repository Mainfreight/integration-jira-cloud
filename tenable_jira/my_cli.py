#!/usr/bin/env python
'''
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
'''
import click
import logging
import time
import yaml
import json
import platform
import sys
from tenable.io import TenableIO
from .config import base_config
from restfly.utils import dict_merge
from .jira import Jira
from .transform import Tio2Jira
from . import __version__
import csv
import os
import arrow
from .scan_downloader import ScanDownloader


@click.command()
@click.option('--download-path', default='/tmp', show_default=True)
@click.option('--setup-only', is_flag=True)
@click.argument('scanname')
@click.argument('configfile', default='config.yaml', type=click.File('r'))
def cli(configfile, scanname, download_path, setup_only=False):
    '''
    Tenable.io -> Jira Cloud Transformer & Ingester
    '''
    config = dict_merge(
        base_config(),
        yaml.load(configfile, Loader=yaml.Loader)
    )

    # Get the logging definition and define any defaults as need be.
    log = config.get('log', {})
    log_lvls = {'debug': 10, 'info': 20, 'warn': 30, 'error': 40}
    log['level'] = log_lvls[log.get('level', 'warn')]
    log['format'] = log.get('format',
                            '%(asctime)-15s %(name)s %(levelname)s %(message)s')

    # Configure the root logging facility
    logging.basicConfig(**log)

    # Output some basic information detailing the config file used and the
    # python version & system arch.
    logging.info('Tenable2JiraCloud Version {}'.format(__version__))
    logging.info('Using configuration file {}'.format(configfile.name))
    uname = platform.uname()
    logging.info('Running on Python {} {}/{}'.format(
        '.'.join([str(i) for i in sys.version_info][0:3]),
        uname[0], uname[-2]))

    # instantiate the Jira object
    jira = Jira(
        'https://{}/rest/api/3'.format(config['jira']['address']),
        config['jira']['api_username'],
        config['jira']['api_token']
    )
    tio = TenableIO(
        access_key=config['tenable'].get('access_key'),
        secret_key=config['tenable'].get('secret_key'),
        vendor='Tenable',
        product='JiraCloud',
        build=__version__
    )

    logging.info('Preparing Jira')
    ingest = Tio2Jira(tio, jira, config)

    if setup_only:
        return
    logging.info('Proceeding to ingest')

    logging.info('Getting latest scan')
    downloader = ScanDownloader(tio)
    latest_scans = downloader.get_latest_scans(scanname)

    logging.info('Downloading scans')
    downloader.download_scans(latest_scans, download_path,
                              ('severity', 'eq', 'Critical'), ('severity', 'eq', 'High'), format='csv', filter_type='or')
    # download_scans(tio, latest_scans, './scdifans', [('severity', 'neq', 'Medium'), ('severity', 'neq', 'Low'), ('severity', 'neq', 'Info')], format='csv', filter_type='and')

    logging.info('Reading scans')
    for s, h in latest_scans:
        f = downloader.scan_file_path(download_path, s, h)
        logging.info('Opening to read: {}'.format(f))
        with open(f, 'r') as scanfile:
            source = csv.DictReader(scanfile, delimiter=',', quotechar='"')
            sevs = [s.title() for s in config['tenable']['tio_severities']]
            hi_source = [r for r in source if r['Risk'] in sevs]
            for row in hi_source:
                logging.info('processing row: {} - {}'.format(row['Plugin ID'], row['Name']))
                ingest._process_open_vuln(row, 'csv_field')
