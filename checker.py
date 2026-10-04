"""Cruising's free, fixed-source link monitor. Python 3.11+, no dependencies."""
import argparse
import ipaddress
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parent
UA = 'CruisingBursaryMonitor/1.0'
MAX_BYTES = 3_000_000

class CheckError(Exception):
    pass

def canonical_url(value):
    u = urlsplit(value)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
        raise ValueError('HTTPS URL required')
    host = u.hostname.lower()
    if '.' not in host or host.endswith(('.local', '.localhost')):
        raise ValueError('Public host required')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('IP address URLs excluded')
    params = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
              if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    # Keep www and trailing slash: some sites give them distinct meanings.
    result = urlunsplit(('https', host, u.path or '/', urlencode(sorted(params)), ''))
    if len(result) > 2000:
        raise ValueError('URL too long')
    return result

class SafeRedirect(HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = set(allowed)
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = canonical_url(newurl)
        if urlsplit(target).hostname not in self.allowed:
            raise CheckError('Redirect outside configured source; review configuration')
        return super().redirect_request(req, fp, code, msg, headers, target)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise CheckError('Database redirect refused')

def fetch_page(url, hosts):
    target = canonical_url(url)
    if urlsplit(target).hostname not in hosts:
        raise CheckError('Source host not allowed')
    opener = build_opener(SafeRedirect(hosts))
    with opener.open(Request(target, headers={'User-Agent': UA, 'Accept': 'text/html,text/plain'}), timeout=15) as r:
        content = r.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise CheckError('Source response exceeds size limit')
        return content.decode(r.headers.get_content_charset() or 'utf-8', errors='replace'), r.geturl()

def allowed_delay(url, hosts, fetch=fetch_page):
    origin = urlsplit(url)
    robots_url = urlunsplit((origin.scheme, origin.netloc, '/robots.txt', '', ''))
    try:
        text, _ = fetch(robots_url, hosts)
    except HTTPError as e:
        if e.code in (404, 410):
            return 1
        raise CheckError('Robots unavailable; source skipped') from None
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    if not parser.can_fetch(UA, url):
        raise CheckError('Robots disallows this page')
    delay = parser.crawl_delay(UA) or 1
    rate = parser.request_rate(UA)
    if rate:
        delay = max(delay, rate.seconds / rate.requests)
    if delay > 15:
        raise CheckError('Source requires a longer interval; manual review needed')
    return delay

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.current = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.current = [attrs.get('href', ''), [attrs.get('title', ''), attrs.get('aria-label', '')]]
        elif tag == 'img' and self.current is not None:
            self.current[1].append(attrs.get('alt', ''))
    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            href, texts = self.current
            self.links.append((href, ' '.join(' '.join(texts).split())))
            self.current = None

def extract_links(html, base, source):
    parser = Links()
    parser.feed(html)
    found = {}
    for href, title in parser.links:
        if not href or href.startswith('#'):
            continue
        try:
            url = canonical_url(urljoin(base, href))
        except (ValueError, TypeError):
            continue
        if url.rstrip('/') == canonical_url(base).rstrip('/'):
            continue
        if not re.search(r'bursar|scholarship', title + ' ' + url, re.I):
            continue
        if re.search(r'/(?:tag|category|page|search)/|/feed/?(?:\?|$)', url, re.I):
            continue
        if urlsplit(url).path.lower().endswith(('.jpg', '.png', '.svg', '.css', '.js')):
            continue
        found[url] = {'url': url, 'title': (title or urlsplit(url).path)[:500],
                      'source_key': source['key'], 'source_url': source['url'], 'status': 'pending_review'}
    if len(found) > 150:
        raise CheckError('Too many links; review source layout')
    return list(found.values())

class Database:
    def __init__(self):
        self.url = os.environ.get('SUPABASE_URL', '').rstrip('/')
        self.key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
        if not re.fullmatch(r'https://[a-z0-9]+\.supabase\.co', self.url) or not self.key:
            raise CheckError('Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in GitHub Actions secrets')
    def post(self, table, data, prefer='return=minimal'):
        req = Request(self.url + '/rest/v1/' + table, method='POST', data=json.dumps(data).encode(), headers={
            'apikey': self.key, 'Authorization': 'Bearer ' + self.key,
            'Content-Type': 'application/json', 'Prefer': prefer})
        try:
            with build_opener(NoRedirect()).open(req, timeout=15) as r:
                body = r.read(MAX_BYTES)
                return json.loads(body) if body else []
        except HTTPError as e:
            raise CheckError('Database HTTP ' + str(e.code) + '; check SQL setup and backend key') from None
    def save(self, items):
        if not items:
            return 0
        rows = self.post('bursary_discoveries?on_conflict=url', items,
                         'resolution=ignore-duplicates,return=representation')
        return len(rows)

def safe_error(e):
    if isinstance(e, CheckError):
        return str(e)
    if isinstance(e, HTTPError):
        return 'Source HTTP ' + str(e.code)
    if isinstance(e, (TimeoutError, URLError)):
        return 'Network request failed or timed out'
    return 'Unexpected ' + type(e).__name__ + '; inspect configuration'

def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument('--dry-run', action='store_true', help='Read websites without database writes')
    args = arg.parse_args()
    try:
        db = None if args.dry_run else Database()
        sources = json.loads((ROOT / 'sources.json').read_text())
    except Exception as e:
        print(safe_error(e))
        return 1
    results = []
    for source in sources:
        if not source.get('enabled'):
            continue
        record = {'source_key': source['key'], 'status': 'failed', 'links_found': 0, 'inserted_count': 0}
        try:
            time.sleep(allowed_delay(source['url'], source['hosts']))
            html, base = fetch_page(source['url'], source['hosts'])
            items = extract_links(html, base, source)
            record.update(status='succeeded' if items else 'warning', links_found=len(items))
            if db:
                record['inserted_count'] = db.save(items)
            if not items:
                record['message'] = 'No matching links extracted; check source manually. This is not proof of no bursaries.'
        except Exception as e:
            record['message'] = safe_error(e)
        record['checked_at'] = datetime.now(timezone.utc).isoformat()
        if db:
            try:
                db.post('bursary_free_runs', record)
            except Exception as e:
                record.update(status='failed', message=safe_error(e))
        results.append(record)
        print(json.dumps(record))
    summary = '\n'.join(f"- {r['source_key']}: {r['status']}; {r['links_found']} links; {r['inserted_count']} new saved" for r in results)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write('## Cruising free checker\n' + summary + '\n\nAll discoveries need review.\n')
    return 1 if not results or any(r['status'] != 'succeeded' for r in results) else 0

if __name__ == '__main__':
    sys.exit(main())
