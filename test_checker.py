import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import checker as c

SOURCE = {'key': 'test', 'url': 'https://example.org/bursaries/'}

class CheckerTests(unittest.TestCase):
    def test_tracking_dedup_and_relative_links(self):
        html = '<a href="/fund-bursary?utm_source=x#one">Fund</a><a href="/fund-bursary">Fund bursary</a><a href="mailto:a@b.org">Bursary</a>'
        rows = c.extract_links(html, SOURCE['url'], SOURCE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], 'https://example.org/fund-bursary')
        self.assertEqual(rows[0]['status'], 'pending_review')
        self.assertNotIn('closing_date', rows[0])
    def test_no_self_or_irrelevant_links(self):
        self.assertEqual(c.extract_links('<a href="/bursaries/">Bursaries</a><a href="/contact">Contact</a>', SOURCE['url'], SOURCE), [])
    def test_image_link_title(self):
        rows = c.extract_links('<a href="/fund"><img alt="ABC scholarship"></a>', SOURCE['url'], SOURCE)
        self.assertEqual(rows[0]['title'], 'ABC scholarship')
    def test_unsafe_urls(self):
        for u in ['http://example.org', 'https://localhost', 'https://127.0.0.1', 'https://user:pass@example.org', 'https://example.org:80']:
            with self.assertRaises(ValueError): c.canonical_url(u)
    def test_robots_denial(self):
        with self.assertRaises(c.CheckError):
            c.allowed_delay(SOURCE['url'], ['example.org'], lambda *_: ('User-agent: *\nDisallow: /', ''))
    def test_robots_failure_is_not_permission(self):
        def deny(*_): raise HTTPError('url', 403, '', {}, None)
        with self.assertRaises(c.CheckError): c.allowed_delay(SOURCE['url'], ['example.org'], deny)
    def test_database_uses_ignore_not_merge(self):
        with patch.dict(os.environ, {'SUPABASE_URL': 'https://test.supabase.co', 'SUPABASE_SERVICE_ROLE_KEY': 'test-key'}):
            db = c.Database()
        with patch.object(db, 'post', return_value=[]) as post:
            self.assertEqual(db.save([{'url': 'https://example.org/bursary'}]), 0)
            self.assertEqual(post.call_args.args[2], 'resolution=ignore-duplicates,return=representation')
    def test_database_never_redirects_secret(self):
        with self.assertRaises(c.CheckError): c.NoRedirect().redirect_request(None, None, None, None, None, None)
    def test_safe_error_does_not_reveal_credentials(self):
        self.assertNotIn('secret-password', c.safe_error(ValueError('secret-password')))

if __name__ == '__main__': unittest.main()
