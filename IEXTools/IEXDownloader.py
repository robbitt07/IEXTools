"""
This module defines the DataDownloader class which finds and downloads the IEX
HIST files that the user requests. If the file cannot be found an exception is
raised.

IEX offers their HIST TOPS and DEEP binary data files on their website. The URL
where these files are located can be retrieved from the IEX web API.
"""
from . import IEXHISTExceptions

from datetime import datetime
import os
import requests
import gzip
import shutil
from typing import Dict


class DataDownloader(object):
    """
    Legacy downloader for IEX HIST files using the IEX API.

    Downloads IEX TOPS and DEEP HIST files using the legacy IEX API.
    This API may no longer be available.

    Parameters
    ----------
    path : str, optional
        Path to the directory where downloaded files will be saved.
        If None, files are saved in the current working directory.

    Attributes
    ----------
    base_endpoint : str
        Base URL for the IEX API.
    directory : str
        Directory where files are saved.

    Note
    ----
    This class uses the legacy IEX API which may not be functional.
    Consider using IEXBulkDownloader for web scraping based downloads.

    Examples
    --------
    >>> downloader = DataDownloader()
    >>> downloader.download(datetime(2023, 1, 1), 'TOPS')
    """

    def __init__(self, path: str = None) -> None:
        """
        Initialize the DataDownloader with API endpoint and directory setup.

        Parameters
        ----------
        path : str, optional
            Path to the directory where downloaded files will be saved.
            If None, uses current working directory.
        """
        self.base_endpoint = "https://api.iextrading.com/1.0/"

        if path:
            self.directory = path
        else:
            self.directory = "IEX_data"
            if not os.path.exists(self.directory):
                os.makedirs(self.directory)

    def _get_endpoint(self, date: datetime) -> str:
        """
        Construct the IEX API endpoint for a given date.

        Parameters
        ----------
        date : datetime
            Date of HIST data being requested.

        Returns
        -------
        str
            URL of IEX API endpoint to send GET request to.
        """
        yyyy = date.year
        mm = str(date.month).zfill(2)
        dd = str(date.day).zfill(2)
        date_str = f"{yyyy}{mm}{dd}"
        endpoint = f"{self.base_endpoint}/hist?date={date_str}"
        return endpoint

    def _get_download_link(self, date: datetime) -> Dict[str, Dict[str, str]]:
        """
        Extract download URL and filename from the IEX API.

        Parameters
        ----------
        date : datetime
            Date of HIST data being requested.

        Returns
        -------
        Dict[str, Dict[str, str]]
            Dictionary containing URL and name of desired file.

        Raises
        ------
        IEXHISTExceptions.RequestsException
            If the API request fails.
        """
        endpoint = self._get_endpoint(date)
        response = requests.get(endpoint)
        try:
            response.raise_for_status()
        except requests.RequestException as e:
            raise IEXHISTExceptions.RequestsException(e.args)

        links: Dict[str, Dict[str, str]] = {}
        for entry in response.json():
            links[entry["feed"]] = {
                "url": entry["link"],
                "file": (
                    f'{entry["date"]}_{entry["protocol"]}_{entry["feed"]}'
                    f'{entry["version"]}.pcap.gz'
                ),
            }

        return links

    def download(self, date: datetime, feed_type: str) -> str:
        """
        Download the pcap file for a given date and feed type.

        Parameters
        ----------
        date : datetime
            Date of desired HIST file.
        feed_type : str
            Type of feed file requested (either TOPS or DEEP).

        Returns
        -------
        str
            Name of downloaded file.

        Raises
        ------
        IEXHISTExceptions.IEXHISTException
            If feed_type is not valid.
        IEXHISTExceptions.RequestsException
            If the download request fails.
        """
        feed_type = feed_type.upper()
        if feed_type not in ["TOPS", "DEEP"]:
            raise IEXHISTExceptions.IEXHISTException(
                "feed_type must be either TOPS or DEEP"
            )

        link_info = self._get_download_link(date)
        url = link_info[feed_type]["url"]
        filename = link_info[feed_type]["file"]
        response = requests.get(url, stream=True)
        try:
            response.raise_for_status()
        except requests.RequestException as e:
            raise IEXHISTExceptions.RequestsException(e.args)

        file_in = os.path.join(self.directory, filename)
        with open(file_in, "wb") as data_file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    data_file.write(chunk)

        return filename

    def decompress(
        self, file_in: str, file_out: str, remove_source: bool = False
    ) -> None:
        """
        Decompress gzip-compressed HIST files.

        Parameters
        ----------
        file_in : str
            Path to the compressed file that needs to be decompressed.
        file_out : str
            Path where the decompressed file will be saved.
        remove_source : bool, default False
            Whether to delete the compressed file after decompression.
        """
        with gzip.open(file_in, "rb") as f_in:
            with open(file_out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        if remove_source:
            os.remove(file_in)

    def download_decompressed(self, date: datetime, feed_type: str) -> str:
        """
        Download and decompress a HIST file in one step.

        Downloads the gzip-compressed pcap file and automatically decompresses
        it, returning the filename of the decompressed file.

        Parameters
        ----------
        date : datetime
            Date of desired HIST file.
        feed_type : str
            Type of feed file requested (either TOPS or DEEP).

        Returns
        -------
        str
            Name of the decompressed file.
        """
        file_name = self.download(date, feed_type)
        file_in = os.path.join(self.directory, file_name)
        file_out = os.path.join(self.directory, file_name.replace(".gz", ""))
        self.decompress(file_in, file_out, remove_source=True)
        return file_name.replace(".gz", "")
