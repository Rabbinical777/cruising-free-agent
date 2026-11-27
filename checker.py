"""Cruising's free, fixed-source link monitor. Python 3.11+, no dependencies."""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import sys
import ssl
import socket
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parent
UA = 'CruisingBursaryMonitor/2.1 (+https://github.com/Rabbinical777/cruising-free-agent)'
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
        if r.headers.get_content_type() not in ('text/html', 'text/plain', 'application/xhtml+xml'):
            raise CheckError('Non-HTML page; manual review needed')
        content = r.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise CheckError('Source response exceeds size limit')
        return content.decode(r.headers.get_content_charset() or 'utf-8', errors='replace'), r.geturl()

def allowed_delay(url, hosts, fetch=fetch_page, cache=None):
    origin = urlsplit(url)
    robots_url = urlunsplit((origin.scheme, origin.netloc, '/robots.txt', '', ''))
    key = origin.netloc.lower()
    if cache is not None and key in cache:
        text = cache[key]          # None means robots.txt does not exist (404/410)
    else:
        try:
            text, _ = fetch(robots_url, hosts)
        except HTTPError as e:
            if e.code not in (404, 410):
                raise CheckError('Robots unavailable; source skipped') from None
            text = None
        if cache is not None:
            cache[key] = text
    if text is None:
        return 1
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
                      'source_key': source['key'], 'source_url': source['url'], 'status': 'pending_review',
                      'tier': source.get('tier', 'lead')}
    if len(found) > 150:
        raise CheckError('Too many links; review source layout')
    return list(found.values())


class PageText(HTMLParser):
    """Extract visible text; ignore scripts, styling and repeated navigation."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer', 'noscript'):
            self.hidden.append(tag)
    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        if not self.hidden and tag in ('p', 'li', 'div', 'h1', 'h2', 'h3', 'tr'):
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

def page_evidence(html):
    parser = PageText()
    parser.feed(html)
    lines = [' '.join(x.split()) for x in ''.join(parser.parts).splitlines()]
    lines = [x for x in lines if x]
    text = '\n'.join(lines)
    if len(text) < 80:
        raise CheckError('Too little visible text; page may require JavaScript')
    # These are excerpts, NOT verified eligibility or parsed dates.
    deadline = [x[:700] for x in lines if re.search(r'closing|deadline|applications? (?:close|open)', x, re.I)][:6]
    requirements = [x[:700] for x in lines if re.search(r'eligib|requirement|citizen|minimum|grade 12|matric|household|qualif', x, re.I)][:10]
    return {'content_hash': hashlib.sha256(text.encode()).hexdigest(),
            'deadline_evidence': deadline, 'requirement_evidence': requirements}

def detail_batch(items, source, day=None):
    # Rotate a bounded batch so all discovered same-host pages get revisited.
    items = sorted([x for x in items if urlsplit(x['url']).hostname in source['hosts']
                    and not urlsplit(x['url']).path.lower().endswith(('.pdf', '.doc', '.docx', '.zip'))
                    and urlsplit(x['url']).path.rstrip('/').lower() not in ('/preregistration', '/login', '/register')],
                   key=lambda x: x['url'])
    if not items:
        return []
    limit = min(int(source.get('detail_limit', 6)), len(items))
    day = datetime.now(timezone.utc).date().toordinal() if day is None else day
    start = day * limit % len(items)
    return [items[(start + i) % len(items)] for i in range(limit)]

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
        except URLError as e:
            raise CheckError('Database unreachable (' + safe_error(e) + '); check SUPABASE_URL and that the '
                             'Supabase project is not paused') from None
    def rpc(self, name):
        return self.post('rpc/' + name, {}, 'return=representation')
    def observe(self, item, evidence):
        return self.post('rpc/record_bursary_page_check', {
            'p_url': item['url'], 'p_hash': evidence['content_hash'],
            'p_deadlines': evidence['deadline_evidence'],
            'p_requirements': evidence['requirement_evidence']}, 'return=representation')

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
    reason = e.reason if isinstance(e, URLError) else e
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'TLS certificate verification failed; secure connection refused'
    if isinstance(reason, ssl.SSLError):
        return 'TLS handshake failed'
    if isinstance(reason, socket.gaierror):
        return 'DNS lookup failed'
    if isinstance(reason, TimeoutError):
        return 'Connection timed out'
    if isinstance(reason, ConnectionRefusedError):
        return 'Connection refused by host'
    if isinstance(reason, ConnectionResetError):
        return 'Connection reset by host'
    if isinstance(e, URLError):
        return 'Network request failed (' + type(reason).__name__ + ')'

    return 'Unexpected ' + type(e).__name__ + '; inspect configuration'

def exit_code(results, db_failed):
    """Fail the run only for real outages, not because one source has a bad day.

    Per-source problems still appear in the run summary and as GitHub warnings."""
    if not results or db_failed:
        return 1
    if all(r['status'] == 'failed' for r in results):
        return 1
    return 0

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
    db_failed = False
    robots_cache = {}
    for source in sources:
        if not source.get('enabled'):
            continue
        record = {'source_key': source['key'], 'status': 'failed', 'links_found': 0, 'inserted_count': 0}
        stage = 'robots_check'
        try:
            time.sleep(allowed_delay(source['url'], source['hosts'], cache=robots_cache))
            stage = 'source_page'
            html, base = fetch_page(source['url'], source['hosts'])
            items = extract_links(html, base, source)
            if source.get('kind') == 'programme':
                items = [{'url': canonical_url(base), 'title': source['title'],
                          'source_key': source['key'], 'source_url': source['url'],
                          'status': 'pending_review', 'tier': source.get('tier', 'lead')}]

            record.update(status='succeeded' if items else 'warning', links_found=len(items))
            if db:
                stage = 'save_discoveries'
                record['inserted_count'] = db.save(items)
            stage = 'detail_pages'
            checked = changed = failed = 0
            for item in detail_batch(items, source):
                try:
                    if item['url'] == canonical_url(base):
                        detail_html = html
                    else:
                        time.sleep(allowed_delay(item['url'], source['hosts'], cache=robots_cache))
                        detail_html, _ = fetch_page(item['url'], source['hosts'])
                    evidence = page_evidence(detail_html)
                    result = db.observe(item, evidence) if db else {}
                    checked += 1
                    changed += int(result.get('changed', False))
                except Exception as e:
                    failed += 1
                    print(json.dumps({'source': source['key'], 'page': item['url'], 'error': safe_error(e)}))
            record['message'] = f'{checked} detail pages checked; {changed} changed; {failed} detail checks failed. Excerpts require review.'
            if failed:
                record['status'] = 'warning'
            if not items:
                record['message'] = 'No matching links extracted; check source manually. This is not proof of no bursaries.'
        except Exception as e:
            record['message'] = stage + ': ' + safe_error(e)
            if stage == 'save_discoveries':
                db_failed = True
        record['checked_at'] = datetime.now(timezone.utc).isoformat()
        if db:
            try:
                db.post('bursary_free_runs', record)
            except Exception as e:
                # Keep the original source error; add the logging failure after it.
                db_failed = True
                record['status'] = 'failed'
                record['message'] = (record.get('message', '') + ' | run log not saved: ' + safe_error(e)).strip(' |')
        results.append(record)
        print(json.dumps(record), flush=True)
        if record['status'] != 'succeeded':
            print(f"::warning title=Source {record['source_key']} {record['status']}::{record.get('message', '')}")
    reminders = 'skipped (dry run)'
    if db:
        try:
            reminders = str(db.rpc('cr_generate_reminders')) + ' reminder(s) created'
        except Exception as e:
            reminders = 'failed: ' + safe_error(e)
            print(f'::warning title=Reminders::{reminders}')
    print('reminders: ' + reminders)
    summary = '\n'.join(f"- {r['source_key']}: {r['status']}; {r['links_found']} links; {r['inserted_count']} new saved; {r.get('message', '')}" for r in results)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write('## Cruising free checker\n' + summary + '\n\nReminders: ' + reminders + '\n\nAll discoveries need review.\n')
    return exit_code(results, db_failed)

if __name__ == '__main__':
    sys.exit(main())
