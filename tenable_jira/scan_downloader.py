import click
import arrow
import os

class ScanDownloader:
    def __init__(self, tio):
        self._tio = tio

    def get_latest_scans(self, search):
        # Get the list of scans that match the name filter defined.
        scans = [s for s in self._tio.scans.list() if search.lower()
                in s['name'].lower()]

        # Get their latest scan history item
        histories = [self.get_latest_completed_history(s) for s in scans]

        # Filter scans for which there are no complete scans
        return [(s, h) for s, h in zip(scans, histories) if h is not None]

    def download_scans(self, latest_scans, path, *filters, **kwargs):
        '''
        Attempts to download the latest completed scan from tenable.io and stores
        the file in the path specified.  The exported scan will be filtered based
        on the filters specified.
        '''

        for scan, latest_scan in latest_scans:
            # download the latest completed scan using the scan name && history id
            # and store the file in the path specified using the filename format:
            # {SCAN_NAME}-{HISTORY_ID}.{FORMAT}
            with open(self.scan_file_path(path, scan, latest_scan), 'wb') as report_file:
                kw = kwargs
                kw['history_id'] = latest_scan['history_id']
                kw['scan_type'] = 'web-app'
                kw['fobj'] = report_file
                click.echo('Scan completed at {} downloading to {}'.format(
                    arrow.get(latest_scan['last_modification_date']).isoformat(),
                    report_file.name))
                click.echo('filters: {}'.format(filters))
                self._tio.scans.export(scan['id'], *filters, **kw)

    def get_latest_completed_history(self, scan):
        details = self._tio.scans.results(scan['id'])

        # get the list of scan histories that are in a completed state.
        completed = [h for h in details.get('history', list())
                    if h.get('status') == 'completed']

        # download the latest completed scan using the scan name && history id
        # and store the file in the path specified using the filename format:
        # {SCAN_NAME}-{HISTORY_ID}.{FORMAT}
        return completed[0] if len(completed) > 0 else None


    def scan_file_path(self, path, scan, history):
        return os.path.join(path, self.scan_file_name(scan, history))


    def scan_file_name(self, scan, history):
        return '{}-{}.csv'.format(
            scan['name'].replace(' ', '_'),
            history['uuid'])