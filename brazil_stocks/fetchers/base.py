"""
Abstract base class for all data fetchers.

Every concrete fetcher must implement `fetch()` which returns a pandas DataFrame.
Additional keyword arguments (e.g. tickers, period) are passed via *fetch_kwargs*.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseFetcher(ABC):
    """Common interface for all data-source fetchers."""

    @abstractmethod
    def fetch(self, **kwargs) -> pd.DataFrame:
        """
        Fetch data and return a normalised pandas DataFrame.

        Concrete implementations must document the columns they return.
        """
        raise NotImplementedError
