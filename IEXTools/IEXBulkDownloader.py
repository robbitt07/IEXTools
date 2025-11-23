"""
This module defines the DataDownloader class which finds and downloads the IEX
HIST files that the user requests. If the file cannot be found an exception is
raised.

IEX offers their HIST TOPS, DEEP, and DPLS binary data files on their website.
Files can be downloaded via:

1. The IEX web API (legacy method - may not work)
2. Direct web scraping from https://iextrading.com/trading/market-data/

Features
--------
- Single file download (legacy API or web scraping)
- Bulk download with filtering by date, feed type, and size
- List available files before downloading
- Dry run mode to preview downloads
- Size filtering to avoid large downloads during testing

Examples
--------
>>> from IEXTools.IEXBulkDownloader import DataDownloader
>>> downloader = DataDownloader()
>>> # List available files
>>> downloader.list_available_files(feed_type='TOPS', limit=5)
>>> # Dry run - see what would be downloaded
>>> downloader.bulk_download('TOPS', max_files=2, dry_run=True)
>>> # Download small files for testing
>>> downloader.bulk_download('TOPS', max_size_gb=1.0, max_files=1)
"""
from . import IEXHISTExceptions
from .options import FileTypeOptions

from datetime import datetime
import os
import requests
import gzip
import shutil
from typing import Dict, List, Optional
from playwright.sync_api import sync_playwright
import re


class DataDownloader(object):

    def __init__(self, path: os.PathLike = None) -> None:
        """
        Initiate the class with the IEX API endpoint information and
        initializes the folder to put the downloaded data into.

        Parameters:
        ----------
        path: os.PathLike, optional
            The path to the directory where the downloaded files will be saved.
            If not provided, the files will be saved in the current working directory.
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
        Constructs the IEX API endpoint that provides the download link for the
        HIST data of a given date.

        Parameters:
        ----------
            date    : date of HIST data being requested

        Returns:
        ----------
            endpoint    : URL of IEX API endpoint to send GET request to
        """
        yyyy = date.year
        mm = str(date.month).zfill(2)
        dd = str(date.day).zfill(2)
        date_str = f"{yyyy}{mm}{dd}"
        endpoint = f"{self.base_endpoint}/hist?date={date_str}"
        return endpoint

    def _get_download_link(self, date: datetime) -> Dict[str, Dict[str, str]]:
        """
        Extract the download URL and filename from the IEX API for the
        requested HIST file.

        Parameters
        ----------
        date : datetime
            Date of HIST data being requested.

        Returns
        -------
        Dict[str, Dict[str, str]]
            Dictionary containing URL and name of desired file.
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
        Downloads the pcap file (either TOPS or DEEP) for a given date and
        returns the filename.

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
            If there is an error downloading the file.
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
        Decompress the gziped HIST files that were downloaded.

        Parameters
        ----------
        file_in : str
            File name that needs to be unzipped.
        file_out : str
            File name of the decompressed file.
        remove_source : bool, default False
            Option to delete the compressed file.
        """
        with gzip.open(file_in, "rb") as f_in:
            with open(file_out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        if remove_source:
            os.remove(file_in)

    def download_decompressed(self, date: datetime, feed_type: str) -> str:
        """
        Single method to both download the gziped pcap file, but also
        decompress it and return the filename of the decompressed pcap file.

        Parameters
        ----------
        date : datetime
            Date of desired HIST file.
        feed_type : str
            Type of feed file requested (either TOPS or DEEP).

        Returns
        -------
        str
            Name of downloaded decompressed file.
        """
        file_name = self.download(date, feed_type)
        file_in = os.path.join(self.directory, file_name)
        file_out = os.path.join(self.directory, file_name.replace(".gz", ""))
        self.decompress(file_in, file_out, remove_source=True)
        return file_name.replace(".gz", "")

    def _scrape_available_files(self, max_rows: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Scrape the IEX website to get all available HIST files.

        Parameters:
        ----------
            max_rows: Optional[int], optional
                Maximum number of rows to process.
                If not provided, all rows will be processed.
        
        Returns:
        ----------
            List of dictionaries containing file information:
            {'date': 'YYYY-MM-DD', 'feed': 'TOPS|DEEP|DPLS',
             'version': 'v1.x', 'protocol': 'IEX-TP v1', 'size': 'XX.XX GB',
             'url': 'download_url'}
            If there is an error scraping the website, an exception will be raised.
        """
        files = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto("https://iextrading.com/trading/market-data/")

                # Wait for the table to load
                page.wait_for_selector("table", timeout=30000)

                # Get all table rows
                rows = page.locator("table tbody tr")
                total_rows = rows.count()
                rows_to_process = min(total_rows, max_rows) if max_rows else total_rows

                print(f"Processing {rows_to_process} of {total_rows} available rows...")

                for i in range(rows_to_process):
                    if i % 100 == 0 and i > 0:
                        print(f"Processed {i}/{rows_to_process} rows...")

                    row = rows.nth(i)
                    cells = row.locator("td")

                    if cells.count() >= 5:
                        date = cells.nth(0).text_content().strip()
                        feed = cells.nth(1).text_content().strip()
                        version = cells.nth(2).text_content().strip()
                        protocol = cells.nth(3).text_content().strip()
                        size = cells.nth(4).text_content().strip()

                        # Get the download link from the row
                        download_link = row.locator("a").first
                        if download_link.count() > 0:
                            url = download_link.get_attribute("href")

                            files.append({
                                "date": date,
                                "feed": feed,
                                "version": version,
                                "protocol": protocol,
                                "size": size,
                                "url": url
                            })

                print(f"Completed scraping {len(files)} files")

            except Exception as e:
                raise IEXHISTExceptions.IEXHISTException(f"Error scraping website: {str(e)}")
            finally:
                browser.close()

        return files

    def get_available_files(self,
                            feed_type: Optional[str] = None,
                            start_date: Optional[datetime] = None,
                            end_date: Optional[datetime] = None,
                            max_size_gb: Optional[float] = None,
                            max_rows: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Get list of available HIST files, optionally filtered by criteria.

        Parameters
        ----------
        feed_type : str, optional
            Type of feed to filter by (TOPS, DEEP, DPLS).
        start_date : datetime, optional
            Earliest date to include.
        end_date : datetime, optional
            Latest date to include.
        max_size_gb : float, optional
            Maximum file size in GB to include (e.g., 0.01 for ~10MB).
        max_rows : int, optional
            Maximum number of rows to scrape from website (for testing).

        Returns
        -------
        List[Dict[str, str]]
            List of available files matching criteria.
        """
        all_files = self._scrape_available_files(max_rows)
        filtered_files = []

        for file_info in all_files:
            # Parse date
            try:
                file_date = datetime.strptime(file_info["date"], "%Y-%m-%d")
            except ValueError:
                continue  # Skip files with invalid dates

            # Parse size
            size_gb = None
            if "size" in file_info and file_info["size"]:
                try:
                    # Extract numeric value from size string like "20.22 GB"
                    size_match = re.match(r"([\d.]+)", file_info["size"])
                    if size_match:
                        size_gb = float(size_match.group(1))
                except (ValueError, AttributeError):
                    pass

            # Apply filters
            if feed_type and file_info["feed"].upper() != feed_type.upper():
                continue

            if start_date and file_date < start_date:
                continue

            if end_date and file_date > end_date:
                continue

            if max_size_gb is not None and size_gb is not None and size_gb > max_size_gb:
                continue

            filtered_files.append(file_info)

        return filtered_files

    def bulk_download(self,
                      feed_type: FileTypeOptions,
                      start_date: Optional[datetime] = None,
                      end_date: Optional[datetime] = None,
                      decompress: bool = False,
                      max_size_gb: Optional[float] = None,
                      max_files: Optional[int] = None,
                      dry_run: bool = False,
                      max_scrape_rows: Optional[int] = None) -> List[str]:
        """
        Bulk download HIST files based on criteria.

        Parameters
        ----------
        feed_type : FileTypeOptions
            Type of feed to download (TOPS, DEEP, DPLS).
        start_date : datetime, optional
            Earliest date to download. If not provided, all available dates are included.
        end_date : datetime, optional
            Latest date to download. If not provided, all available dates are included.
        decompress : bool, default False
            Whether to decompress files after download.
        max_size_gb : float, optional
            Maximum file size in GB to download (e.g., 0.01 for ~10MB).
        max_files : int, optional
            Maximum number of files to download (for testing).
        dry_run : bool, default False
            If True, only list files that would be downloaded.
        max_scrape_rows : int, optional
            Maximum number of rows to scrape from website (for testing).

        Returns
        -------
        List[str]
            List of downloaded filenames (or would-be downloaded in dry_run mode).

        Raises
        ------
        IEXHISTExceptions.IEXHISTException
            If feed_type is not valid.
        IEXHISTExceptions.RequestsException
            If there is an error downloading the files.
        """
        feed_type = feed_type.upper()
        if feed_type not in ["TOPS", "DEEP", "DPLS"]:
            raise IEXHISTExceptions.IEXHISTException(
                "feed_type must be either TOPS, DEEP, or DPLS"
            )

        available_files = self.get_available_files(feed_type, start_date, end_date, max_size_gb, max_scrape_rows)

        if max_files:
            available_files = available_files[:max_files]

        if dry_run:
            print(f"Dry run: Would download {len(available_files)} files:")
            for file_info in available_files:
                print(f"  {file_info['date']} {file_info['feed']} - {file_info['size']}")
            return [f"{file_info['date']}_{file_info['feed']}" for file_info in available_files]

        downloaded_files = []
        total_size_gb = 0

        for file_info in available_files:
            try:
                # Parse size for progress tracking
                size_gb = 0
                if "size" in file_info and file_info["size"]:
                    try:
                        size_match = re.match(r"([\d.]+)", file_info["size"])
                        if size_match:
                            size_gb = float(size_match.group(1))
                    except (ValueError, AttributeError):
                        pass

                print(f"Downloading: {file_info['date']} {file_info['feed']} - {file_info['size']}")
                total_size_gb += size_gb

                # Convert date string to datetime for the existing download method
                file_date = datetime.strptime(file_info["date"], "%Y-%m-%d")

                if decompress:
                    filename = self.download_decompressed(file_date, feed_type)
                else:
                    filename = self.download(file_date, feed_type)

                downloaded_files.append(filename)
                print(f"✓ Downloaded: {filename}")

            except Exception as e:
                print(f"✗ Error downloading {file_info['date']} {feed_type}: {str(e)}")
                continue

        print(f"\nBulk download complete: {len(downloaded_files)}/{len(available_files)} files downloaded")
        print(f"Total size downloaded: ~{total_size_gb:.2f} GB")
        return downloaded_files

    def test_download_small_files(self,
                                  feed_type: FileTypeOptions = "TOPS",
                                  max_files: int = 1,
                                  decompress: bool = False) -> List[str]:
        """
        Convenience method for testing with small files.

        Parameters
        ----------
        feed_type : FileTypeOptions, default "TOPS"
            Type of feed to download (TOPS, DEEP, DPLS).
        max_files : int, default 1
            Maximum number of files to download.
        decompress : bool, default False
            Whether to decompress files after download.

        Returns
        -------
        List[str]
            List of downloaded filenames.

        Raises
        ------
        IEXHISTExceptions.IEXHISTException
            If no small files are found under 1GB.
        """
        # Find files smaller than 100MB for testing
        available_files = self.get_available_files(feed_type=feed_type, max_size_gb=0.1)

        if not available_files:
            print("No small test files found. Trying with slightly larger files...")
            available_files = self.get_available_files(feed_type=feed_type, max_size_gb=1.0)

        if not available_files:
            raise IEXHISTExceptions.IEXHISTException(
                f"No {feed_type} files found under 1GB. Try using bulk_download with max_size_gb parameter."
            )

        # Sort by size (smallest first) and take the requested number
        available_files.sort(key=lambda x: float(re.match(r"([\d.]+)", x["size"]).group(1)) if re.match(r"([\d.]+)", x["size"]) else 999)
        test_files = available_files[:max_files]

        print(f"Testing with {len(test_files)} small files:")
        for file_info in test_files:
            print(f"  {file_info['date']} {file_info['feed']} - {file_info['size']}")

        return self.bulk_download(feed_type, max_files=max_files, decompress=decompress)

    def list_available_files(self,
                             feed_type: Optional[str] = None,
                             start_date: Optional[datetime] = None,
                             end_date: Optional[datetime] = None,
                             max_size_gb: Optional[float] = None,
                             limit: Optional[int] = None,
                             max_scrape_rows: Optional[int] = None) -> None:
        """
        Display available HIST files in a readable format.

        Parameters
        ----------
        feed_type : str, optional
            Type of feed to filter by (TOPS, DEEP, DPLS).
        start_date : datetime, optional
            Earliest date to include.
        end_date : datetime, optional
            Latest date to include.
        max_size_gb : float, optional
            Maximum file size in GB to include.
        limit : int, optional
            Maximum number of files to display.
        max_scrape_rows : int, optional
            Maximum number of rows to scrape from website (for testing).
        """
        files = self.get_available_files(feed_type, start_date, end_date, max_size_gb, max_scrape_rows)

        if limit:
            files = files[:limit]

        if not files:
            print("No files found matching criteria.")
            return

        print(f"\nFound {len(files)} available files:")
        print("-" * 80)
        print(f"{'Date':<12} {'Feed':<6} {'Version':<8} {'Size':<12} {'Protocol'}")
        print("-" * 80)

        for file_info in files:
            date = file_info["date"]
            feed = file_info["feed"]
            version = file_info["version"]
            size = file_info["size"]
            protocol = file_info["protocol"]

            print(f"{date:<12} {feed:<6} {version:<8} {size:<12} {protocol}")

        print("-" * 80)

        # Summary statistics
        feed_counts = {}
        total_size = 0

        for file_info in files:
            feed = file_info["feed"]
            feed_counts[feed] = feed_counts.get(feed, 0) + 1

            # Parse size
            if "size" in file_info and file_info["size"]:
                try:
                    size_match = re.match(r"([\d.]+)", file_info["size"])
                    if size_match:
                        total_size += float(size_match.group(1))
                except (ValueError, AttributeError):
                    pass

        print(f"Summary: {feed_counts}")
        print(f"Total estimated size: {total_size:.2f} GB")
        print("\nUse bulk_download() to download these files.")
        print("Example: downloader.bulk_download('TOPS', max_files=2, dry_run=True)")
