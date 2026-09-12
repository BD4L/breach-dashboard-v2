"""Sources carried over from both original projects, with explicit collection scope."""

FEEDS = {
    'news_krebs': ('KrebsOnSecurity', 'https://krebsonsecurity.com/feed/'),
    'news_bleepingcomputer': ('BleepingComputer', 'https://www.bleepingcomputer.com/feed/'),
    'news_hackernews': ('The Hacker News', 'https://feeds.feedburner.com/TheHackersNews'),
    'news_securityweek': ('SecurityWeek', 'https://www.securityweek.com/feed/'),
    'news_threatpost': ('Threatpost', 'https://threatpost.com/feed/'),
    'news_darkreading': ('Dark Reading', 'https://www.darkreading.com/rss.xml'),
    'news_databreaches': ('DataBreaches.net', 'https://databreaches.net/feed/'),
    'news_cybersecurityventures': ('Cybersecurity Ventures', 'https://cybersecurityventures.com/feed/'),
    'reddit_cybersecurity': ('Reddit r/cybersecurity', 'https://www.reddit.com/r/cybersecurity.rss'),
    'reddit_databreaches': ('Reddit r/databreaches', 'https://www.reddit.com/r/databreaches.rss'),
    'news_cybernews': ('Cybernews', 'https://cybernews.com/'),
    'news_securitymagazine': ('Security Magazine Cybersecurity', 'https://www.securitymagazine.com/rss/topic/2236-cybersecurity-news'),
    'cisa_news': ('CISA News', 'https://www.cisa.gov/news.xml'),
    'cisa_advisories': ('CISA Cybersecurity Alerts', 'https://www.cisa.gov/cybersecurity-advisories/all.xml'),
    'news_databreachtoday': ('DataBreachToday.com', 'https://www.databreachtoday.com/rssFeeds.php?type=main'),
    'news_healthcareinfosecurity': ('HealthcareInfoSecurity.com', 'https://www.healthcareinfosecurity.com/rssFeeds.php?type=main'),
    'news_bankinfosecurity': ('BankInfoSecurity.com', 'https://www.bankinfosecurity.com/rssFeeds.php?type=main'),
    'news_inforisktoday': ('InfoRiskToday.com', 'https://www.inforisktoday.com/rssFeeds.php?type=main'),
    'hibp_feed': ('Have I Been Pwned — latest breaches feed', 'https://feeds.feedburner.com/HaveIBeenPwnedLatestBreaches'),
    'news_sans': ('SANS Internet Storm Center', 'https://isc.sans.edu/rssfeed.xml'),
}

COMPANY_PAGES = {
    'ir_microsoft': ('Microsoft IR', 'https://www.microsoft.com/en-us/investor/default'),
    'ir_apple': ('Apple IR', 'https://investor.apple.com/investor-relations/default.aspx'),
    'ir_amazon': ('Amazon IR', 'https://ir.aboutamazon.com/'),
    'ir_alphabet': ('Alphabet IR', 'https://abc.xyz/investor/'),
    'ir_meta': ('Meta IR', 'https://investor.atmeta.com/'),
}

HIBP_ATTRIBUTION = {
    'name': 'Have I Been Pwned', 'url': 'https://haveibeenpwned.com/',
    'license': 'CC BY 4.0', 'licenseUrl': 'https://creativecommons.org/licenses/by/4.0/',
    'changes': 'Public breach metadata normalized and filtered; no account, password or domain searches.',
}

SOURCES = {
    'vermont': {'id': 'vermont', 'label': 'Vermont', 'jurisdiction': 'VT',
                'method': 'Current official reporting table',
                'homepage': 'https://ago.vermont.gov/categories/security-breach-notices'},
    'hawaii': {'id': 'hawaii', 'label': 'Hawaii', 'jurisdiction': 'HI',
               'method': 'Official notification table',
               'homepage': 'https://cca.hawaii.gov/ocp/notices/security-breach/'},
    'hibp': {'id': 'hibp', 'label': 'Have I Been Pwned', 'jurisdiction': 'Global',
             'method': 'Public breach catalog API', 'category': 'secondary',
             'homepage': 'https://haveibeenpwned.com/PwnedWebsites', 'attribution': HIBP_ATTRIBUTION},
    'breachsense': {'id': 'breachsense', 'label': 'Breachsense', 'jurisdiction': 'Global',
                    'method': 'Public ransomware claim index', 'category': 'claims',
                    'homepage': 'https://www.breachsense.com/breaches/'},
}
for identifier, (label, url) in FEEDS.items():
    SOURCES[identifier] = {'id': identifier, 'label': label, 'jurisdiction': 'Global',
                           'method': 'Community feed' if identifier.startswith('reddit_') else 'News / metadata feed',
                           'category': 'secondary', 'homepage': url}
SOURCES['hibp_feed']['attribution'] = HIBP_ATTRIBUTION
SOURCES['news_cybernews']['method'] = 'Current public news cards; limited scope'
for identifier, (label, url) in COMPANY_PAGES.items():
    SOURCES[identifier] = {'id': identifier, 'label': label, 'jurisdiction': 'US',
                           'method': 'Company announcement page; limited scope',
                           'category': 'secondary', 'homepage': url}
for identifier, label, url, reason in [
    ('cisa_kev', 'CISA Known Exploited Vulnerabilities', 'https://www.cisa.gov/known-exploited-vulnerabilities-catalog',
     'Reference source from the original project. Vulnerability listings do not establish an organization data breach and are not imported as breach reports.'),
    ('nvd', 'NIST National Vulnerability Database', 'https://nvd.nist.gov/',
     'Reference source from the original project. CVEs are vulnerability records, not organization breach notices; use the original catalog for vulnerability research.'),
    ('privacy_rights', 'Privacy Rights Clearinghouse', 'https://privacyrights.org/data-breaches',
     'The original CSV importer has no current public live feed. The provider offers a purchased database and historical samples; no licensed dataset has been configured.'),
]:
    SOURCES[identifier] = {'id': identifier, 'label': label, 'jurisdiction': 'US',
                           'method': 'Reference catalog', 'category': 'reference', 'homepage': url,
                           'collectionEnabled': False, 'disabledReason': reason}


def expected_signal(metadata: dict) -> str | None:
    category = metadata.get('category', 'claims' if metadata['id'] == 'ransomlook' else 'official')
    return {'claims': 'ransomware_claim', 'secondary': 'secondary_report'}.get(category)
