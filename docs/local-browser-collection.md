# Optional local browser collection

New Hampshire, New Jersey and SEC currently load in an ordinary local Chrome
session with JavaScript disabled. This does not prove unattended GitHub access.
The regular scheduled collectors and workflows continue to use public HTTP.

Install the normal Python requirements and then the separate optional browser
lock. An installed Google Chrome is required; no profile or login is reused.

```sh
python -m pip install -r requirements.lock -r requirements-browser.lock
python -m ingestion.local_browser fetch --source new_hampshire --max-pages 30 --output state/local/new_hampshire.json
python -m ingestion.local_browser fetch --source new_jersey --output state/local/new_jersey.json
python -m ingestion.local_browser fetch --source sec --output state/local/sec.json
```

These commands create local result envelopes only. They do not merge a database,
write GitHub, publish Pages, or schedule another run. A partial source produces
exit status 1 while retaining its valid collected records in the envelope.
Inspect the message, counts and evidence before a separately authorized merge.
SEC scans its existing 30-day filing window; NH defaults to 30 pages of 25 rows.
`--timeout` defaults to 600 seconds and accepts up to 900 seconds. The supervisor
terminates the worker and its detached Chrome descendants at the hard deadline.

Each invocation creates a fresh headed Chrome context with strict TLS,
JavaScript disabled, service workers blocked and downloads disabled. No cookies,
credentials, proxy, custom user agent, persistent profile or challenge interaction
is supplied. Cookies are cleared between pages. Requests are at least one second
apart, each navigation has a 30-second deadline and a 6 MB response limit, and
the source also has total request/byte/time limits.

CDP Fetch request-stage interception permits only one approved main-frame GET
per navigation. Redirect hops, additional frames and subresources are blocked
before their HTTP request proceeds. Only the three fixed source path/query
contracts are accepted; the CLI has no arbitrary-URL option. Denials stop without
retry. HTML/JSON response bytes feed the existing source parsers, and envelopes
explicitly identify the local-browser transport.

Pure boundary tests run in the regular test suite without importing Playwright.
The separate opt-in local network proof uses a controlled loopback server to
verify that HTTP 302/307 destinations, iframe/script/image URLs and cookie carry
receive no requests. It does not contact an external service or install a CA:

```sh
BREACH_RUN_BROWSER_TESTS=1 python -m unittest tests.test_local_browser -v
```

The `_worker` command is internal to the deadline supervisor. Use `fetch` for
collection. The optional dependency lock is never installed by the default
GitHub collection workflow.
