import contextlib
import io
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import checker as c

SOURCE = {'key': 'test', 'url': 'https://example.org/bursaries/', 'tier': 'official'}
PAGE = '<a href="/fund-bursary">Fund bursary</a>' + '<p>Some visible text about the programme. ' * 5 + '</p>'


class TierTests(unittest.TestCase):
    def test_discovered_links_carry_source_tier(self):
        rows = c.extract_links('<a href="/fund-bursary">Fund bursary</a>', SOURCE['url'], SOURCE)
        self.assertEqual(rows[0]['tier'], 'official')

    def test_tier_defaults_to_lead(self):
        src = {'key': 'x', 'url': SOURCE['url']}
        rows = c.extract_links('<a href="/fund-bursary">Fund bursary</a>', src['url'], src)
        self.assertEqual(rows[0]['tier'], 'lead')

    def test_sources_json_aggregators_are_leads(self):
        sources = json.loads((c.ROOT / 'sources.json').read_text())
        tiers = {s['key']: s['tier'] for s in sources}
        for key in ('studytrust', 'careerwise', 'zabursaries'):
            self.assertEqual(tiers[key], 'lead')
        for key in ('funza_lushaka', 'dffe'):
            self.assertEqual(tiers[key], 'official')


class RobotsCacheTests(unittest.TestCase):
    def test_robots_fetched_once_per_origin(self):
        calls = []
        def fetch(url, hosts):
            calls.append(url)
            return 'User-agent: *\nAllow: /', ''
        cache = {}
        c.allowed_delay('https://example.org/a', ['example.org'], fetch, cache)
        c.allowed_delay('https://example.org/b', ['example.org'], fetch, cache)
        self.assertEqual(len(calls), 1)

    def test_missing_robots_is_cached_and_allowed(self):
        calls = []
        def fetch(url, hosts):
            calls.append(url)
            raise HTTPError(url, 404, '', {}, None)
        cache = {}
        self.assertEqual(c.allowed_delay('https://example.org/a', ['example.org'], fetch, cache), 1)
        self.assertEqual(c.allowed_delay('https://example.org/b', ['example.org'], fetch, cache), 1)
        self.assertEqual(len(calls), 1)

    def test_cached_robots_still_denies(self):
        def fetch(url, hosts):
            return 'User-agent: *\nDisallow: /private', ''
        cache = {}
        c.allowed_delay('https://example.org/open', ['example.org'], fetch, cache)
        with self.assertRaises(c.CheckError):
            c.allowed_delay('https://example.org/private/x', ['example.org'], fetch, cache)


class ExitCodeTests(unittest.TestCase):
    def test_one_bad_source_does_not_fail_the_run(self):
        self.assertEqual(c.exit_code([{'status': 'succeeded'}, {'status': 'failed'}, {'status': 'warning'}], False), 0)

    def test_all_sources_failed_fails_the_run(self):
        self.assertEqual(c.exit_code([{'status': 'failed'}, {'status': 'failed'}], False), 1)

    def test_database_failure_fails_the_run(self):
        self.assertEqual(c.exit_code([{'status': 'succeeded'}], True), 1)

    def test_no_results_fails_the_run(self):
        self.assertEqual(c.exit_code([], False), 1)


class DatabaseErrorTests(unittest.TestCase):
    def make_db(self):
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://test.supabase.co', 'SUPABASE_SERVICE_ROLE_KEY': 'test-key'}):
            return c.Database()

    def test_unreachable_database_message_names_likely_causes(self):
        db = self.make_db()
        class Opener:
            def open(self, *a, **k):
                raise URLError(socket.gaierror(-2, 'Name or service not known'))
        with patch.object(c, 'build_opener', return_value=Opener()):
            with self.assertRaises(c.CheckError) as ctx:
                db.post('bursary_free_runs', {})
        msg = str(ctx.exception)
        self.assertIn('DNS lookup failed', msg)
        self.assertIn('paused', msg)
        self.assertNotIn('test-key', msg)

    def test_rpc_posts_to_rpc_path(self):
        db = self.make_db()
        with patch.object(db, 'post', return_value=3) as post:
            self.assertEqual(db.rpc('cr_generate_reminders'), 3)
            self.assertEqual(post.call_args.args[0], 'rpc/cr_generate_reminders')


class FakeDb:
    """Stands in for the database when the connection is down."""
    def save(self, items):
        raise c.CheckError('Database unreachable (DNS lookup failed); check SUPABASE_URL')
    def post(self, table, data, prefer=''):
        raise c.CheckError('Database unreachable (DNS lookup failed); check SUPABASE_URL')
    def rpc(self, name):
        raise c.CheckError('Database unreachable (DNS lookup failed); check SUPABASE_URL')
    def observe(self, item, evidence):
        raise c.CheckError('Database unreachable')


class MainTests(unittest.TestCase):
    def run_main(self, sources):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'sources.json').write_text(json.dumps(sources))
            with patch.object(c, 'ROOT', Path(d)), patch.object(c, 'Database', FakeDb), \
                 patch.object(c, 'allowed_delay', return_value=0), \
                 patch.object(c, 'fetch_page', return_value=(PAGE, SOURCE['url'])), \
                 patch.object(c.time, 'sleep'), patch('sys.argv', ['checker.py']), \
                 contextlib.redirect_stdout(out):
                code = c.main()
        lines = [json.loads(x) for x in out.getvalue().splitlines() if x.startswith('{') and 'source_key' in x]
        return code, lines, out.getvalue()

    def test_database_outage_keeps_original_error_and_fails_run(self):
        src = {'key': 'test', 'url': SOURCE['url'], 'hosts': ['example.org'], 'enabled': True}
        code, records, text = self.run_main([src])
        self.assertEqual(code, 1)
        msg = records[0]['message']
        self.assertIn('save_discoveries', msg)      # original stage is kept
        self.assertIn('run log not saved', msg)     # and the logging failure is added
        self.assertEqual(records[0]['status'], 'failed')
        self.assertIn('::warning', text)


class SourcesFileTests(unittest.TestCase):
    def setUp(self):
        self.sources = json.loads((c.ROOT / 'sources.json').read_text())

    def test_keys_are_unique(self):
        keys = [s['key'] for s in self.sources]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_source_url_is_safe_and_on_an_allowed_host(self):
        from urllib.parse import urlsplit
        for s in self.sources:
            host = urlsplit(c.canonical_url(s['url'])).hostname
            self.assertIn(host, s['hosts'], s['key'])

    def test_every_source_has_a_valid_tier(self):
        for s in self.sources:
            self.assertIn(s.get('tier'), ('official', 'lead'), s['key'])

    def test_programme_sources_have_a_title(self):
        for s in self.sources:
            if s.get('kind') == 'programme':
                self.assertTrue(s.get('title'), s['key'])

    def test_no_aggregator_is_marked_official(self):
        for s in self.sources:
            if s['key'] in ('studytrust', 'careerwise', 'zabursaries'):
                self.assertEqual(s['tier'], 'lead')


if __name__ == '__main__':
    unittest.main()
