#!/usr/bin/env python3
"""
sn.py — ServiceNow HTTP client and GitHub Actions output helpers.

Shared by all scripts in .github/scripts/. Because Python adds the script's
own directory to sys.path when run directly, importing is simply:

    from sn import ServiceNowClient, gha_output, gha_output_multiline, gha_summary
"""
import os
import sys
import time

import requests


class ServiceNowClient:
    """HTTP client for ServiceNow REST APIs. Initialized with instance URL and basic auth credentials."""

    def __init__(self, instance: str, user: str, password: str):
        self.instance = instance
        self.base_url = f'https://{instance}.service-now.com'
        self._session = requests.Session()
        self._session.auth = (user, password)

    @classmethod
    def from_env(cls, prefix: str = 'SN') -> 'ServiceNowClient':
        """
        Create a client from environment variables.
          prefix='SN'     → SN_INSTANCE,      SN_USER,      SN_PASS
          prefix='SN_DEV' → SN_DEV_INSTANCE,  SN_DEV_USER,  SN_DEV_PASS
          prefix='SN_TEST'→ SN_TEST_INSTANCE, SN_TEST_USER, SN_TEST_PASS
        """
        return cls(
            os.environ[f'{prefix}_INSTANCE'],
            os.environ[f'{prefix}_USER'],
            os.environ[f'{prefix}_PASS'],
        )

    def get_json(self, path: str) -> dict:
        """GET a Table API path and return parsed JSON. Exits on HTTP error."""
        url = self.base_url + path
        resp = self._session.get(url, headers={'Accept': 'application/json'}, timeout=60)
        if not resp.ok:
            print(f'::error::GET {url} returned HTTP {resp.status_code}.')
            sys.exit(1)
        return resp.json()

    def post_json(self, path: str, body: dict) -> dict:
        """POST JSON to a Table API path and return parsed JSON. Exits on HTTP error."""
        url = self.base_url + path
        resp = self._session.post(
            url,
            json=body,
            headers={'Accept': 'application/json'},
            timeout=60,
        )
        if not resp.ok:
            print(f'::error::POST {url} returned HTTP {resp.status_code}: {resp.text[:300]}')
            sys.exit(1)
        return resp.json()

    def post(self, path: str) -> None:
        """
        POST with an empty body to a legacy .do processor endpoint.
        Raises requests.HTTPError on failure — callers decide if fatal.
        """
        url = self.base_url + path
        resp = self._session.post(url, data=b'', timeout=120)
        resp.raise_for_status()

    def poll_progress(
        self,
        progress_id: str,
        timeout: int = 300,
        interval: int = 10,
        operation: str = 'operation',
    ) -> None:
        """
        Poll a CI/CD progress record until it succeeds.
        Prints progress to stdout. Exits with code 1 on failure or timeout.

        Status codes: 0=Pending, 1=Running, 2=Successful, 3=Failed, 4=Cancelled
        """
        elapsed = 0
        while True:
            prog         = self.get_json(f'/api/sn_cicd/progress/{progress_id}').get('result', {})
            status       = int(prog.get('status', 0))
            pct          = prog.get('percent_complete', 0)
            status_label = prog.get('status_label', '')
            print(f'  [{elapsed}s] {pct}% — {status_label}')

            if status == 2:
                return
            if status >= 3:
                detail = prog.get('status_detail') or prog.get('error') or prog.get('status_message', '')
                print(f'::error::{operation} failed ({status_label}): {detail}')
                sys.exit(1)

            if elapsed >= timeout:
                print(f'::error::{operation} timed out after {timeout}s.')
                sys.exit(1)

            time.sleep(interval)
            elapsed += interval


# ---------------------------------------------------------------------------
# GitHub Actions output helpers
# ---------------------------------------------------------------------------

def gha_output(key: str, value: str) -> None:
    """Append a single-line key=value pair to $GITHUB_OUTPUT."""
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'{key}={value}\n')


def gha_output_multiline(key: str, value: str) -> None:
    """Append a multiline value to $GITHUB_OUTPUT using heredoc syntax."""
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'{key}<<__EOF__\n{value}\n__EOF__\n')


def gha_summary(text: str) -> None:
    """Append text to $GITHUB_STEP_SUMMARY."""
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
        f.write(text)
