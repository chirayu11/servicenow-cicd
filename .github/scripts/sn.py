#!/usr/bin/env python3
"""
sn.py — ServiceNow HTTP client and GitHub Actions output helpers.

Shared by all scripts in .github/scripts/. Because Python adds the script's
own directory to sys.path when run directly, importing is simply:

    from sn import ServiceNowClient, gha_output, gha_output_multiline, gha_summary
"""
import os
import re
import sys

import requests


class ServiceNowClient:
    """HTTP client for the ServiceNow REST API and legacy .do endpoints.

    Uses requests.Session so that cookies established by the first Table API
    call (which accepts Basic Auth) are automatically reused by subsequent
    legacy .do processor calls (which require a server-side session cookie).
    """

    def __init__(self, instance: str, user: str, password: str):
        self.instance = instance
        self.base_url = f'https://{instance}.service-now.com'
        self._user = user
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

    def get_raw(self, path: str, accept: str = 'application/xml') -> bytes:
        """GET a path and return the raw response body. Exits on HTTP error."""
        url = self.base_url + path
        resp = self._session.get(url, headers={'Accept': accept}, timeout=120)
        if not resp.ok:
            print(f'::error::GET {url} returned HTTP {resp.status_code}.')
            sys.exit(1)
        return resp.content

    def post(self, path: str) -> None:
        """
        POST with an empty body to a legacy .do processor endpoint.
        Raises requests.HTTPError on failure — callers decide if fatal.
        """
        url = self.base_url + path
        resp = self._session.post(url, data=b'', timeout=120)
        resp.raise_for_status()

    def upload_xml(self, path: str, file_path: str) -> requests.Response:
        """
        POST a multipart/form-data XML file upload to a legacy .do processor.

        ServiceNow Jelly processors require a CSRF token (sysparm_ck / g_ck).
        Without it the processor re-renders the form page with HTTP 200 and
        creates nothing. We GET the page first to extract the token, then POST.

        Returns the full Response so callers can inspect status_code, url, and text.
        """
        url = self.base_url + path

        # Extract the CSRF token from the upload form page.
        page = self._session.get(url, timeout=60)
        m = re.search(r"var g_ck\s*=\s*['\"]([a-f0-9]+)['\"]", page.text)
        if m:
            sysparm_ck = m.group(1)
            print(f'Extracted sysparm_ck: {sysparm_ck[:8]}…')
        else:
            sysparm_ck = ''
            print('::warning::Could not extract sysparm_ck from upload page — proceeding without CSRF token.')

        with open(file_path, 'rb') as f:
            return self._session.post(
                url,
                data={'sysparm_ck': sysparm_ck},
                files={'attachmentFile': ('update_set.xml', f, 'application/xml')},
                allow_redirects=True,
                timeout=120,
            )


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
