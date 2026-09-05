"""Bounded, identifiable public-source HTTP client; no access-control workarounds."""
from __future__ import annotations

from dataclasses import dataclass
import time
from urllib.parse import urljoin, urlsplit

import requests
from requests.auth import AuthBase

from ingestion.models import SourceError


@dataclass
class Response:
    url: str
    content: bytes
    content_type: str

    @property
    def text(self) -> str:
        return self.content.decode('utf-8-sig', errors='replace')


class PublicOnlyAuth(AuthBase):
    """Disable Requests' implicit .netrc authentication for anonymous public reads."""
    def __call__(self, request):
        request.headers.pop('Authorization', None)
        return request


class PublicClient:
    def __init__(self, *, max_requests: int = 24, max_bytes: int = 15_000_000,
                 deadline_seconds: int = 240, session=None):
        self.session = session or requests.Session()
        self.session.auth = PublicOnlyAuth()
        self.session.headers.update({'User-Agent': 'BreachDashboardPilot/0.1 (public breach report collector)',
                                     'Accept': 'text/html,application/pdf,text/csv,application/xml;q=0.9,*/*;q=0.5'})
        self.max_requests = max_requests
        self.max_bytes = max_bytes
        self.requests = 0
        self.bytes = 0
        self.deadline = time.monotonic() + deadline_seconds
        self.last_request_at = None

    def close(self):
        self.session.close()

    def request(self, url: str, *, data=None, headers=None) -> Response:
        """Retry transient failures once. Stop immediately on 401/403/429."""
        method = 'POST' if data is not None else 'GET'
        for redirect in range(5):
            parts = urlsplit(url)
            if parts.scheme != 'https' or parts.username or parts.password or parts.port not in (None, 443):
                raise SourceError('Source supplied an unsafe/non-HTTPS URL')
            host = parts.hostname or ''
            if not (host in {'www.mass.gov', 'mass.gov', 'ocrportal.hhs.gov', 'oag.ca.gov'}
                    or (host.endswith('.amazonaws.com') and method == 'GET')):
                raise SourceError('Source redirected outside the permitted official document hosts')
            for attempt in range(2):
                if self.requests >= self.max_requests or time.monotonic() >= self.deadline:
                    raise SourceError('Public source request/time budget exhausted')
                if self.last_request_at is not None:
                    time.sleep(max(0, 0.4 - (time.monotonic() - self.last_request_at)))
                self.last_request_at = time.monotonic()
                self.requests += 1
                try:
                    # Requests honors REQUESTS_CA_BUNDLE; never disable certificate verification.
                    response = self.session.request(method, url, data=data, headers=headers,
                                                    timeout=(10, 30), allow_redirects=False, stream=True)
                    with response:
                        if response.status_code in (401, 403, 429):
                            raise SourceError(f'HTTP {response.status_code} from {host}; collection stopped without bypass or retry')
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get('Location')
                            if not location:
                                raise SourceError('Source redirect omitted its destination')
                            url = urljoin(url, location)
                            if response.status_code in (301, 302, 303):
                                method, data = 'GET', None
                            break
                        if response.status_code >= 500 and attempt == 0:
                            time.sleep(1)
                            continue
                        if response.status_code != 200:
                            raise SourceError(f'HTTP {response.status_code} from {host}')
                        chunks = []
                        for chunk in response.iter_content(64 * 1024):
                            self.bytes += len(chunk)
                            if self.bytes > self.max_bytes or time.monotonic() >= self.deadline:
                                raise SourceError('Public source response exceeded byte/time budget')
                            chunks.append(chunk)
                        content = b''.join(chunks)
                        if not content:
                            raise SourceError('Public source returned an empty response')
                        return Response(url, content, response.headers.get('Content-Type', ''))
                except requests.exceptions.SSLError as exc:
                    raise SourceError(f'TLS certificate validation failed for {host}; configure a trusted CA bundle') from exc
                except requests.RequestException as exc:
                    if attempt == 0:
                        time.sleep(1)
                        continue
                    raise SourceError(f'Public source request failed for {host}: {type(exc).__name__}') from exc
            else:
                raise SourceError(f'Public source retry budget exhausted for {host}')
        raise SourceError('Public source exceeded redirect limit')
