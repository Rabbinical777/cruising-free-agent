import unittest
from checker import page_evidence, detail_batch, CheckError

class UpgradeTests(unittest.TestCase):
    def test_evidence_and_change(self):
        body = '<p>Applications close 31 October 2026. Check the current funding round before applying.</p><p>Minimum requirements: South African citizenship and a completed matric certificate.</p>'
        a = page_evidence(body)
        self.assertIn('31 October 2026', a['deadline_evidence'][0])
        self.assertIn('citizenship', a['requirement_evidence'][0])
        self.assertNotEqual(a['content_hash'], page_evidence(body.replace('31 October', '30 November'))['content_hash'])
        self.assertEqual(a, page_evidence(body + '<script>new Date()</script><nav>random menu</nav>'))
    def test_no_invented_dates(self):
        e = page_evidence('<p>Applications will open soon. Please check the provider for the next funding round and details of their bursary.</p>')
        self.assertNotIn('closing_date', e)
    def test_rotation_reaches_every_page(self):
        items=[{'url':f'https://example.org/{i}'} for i in range(34)]
        src={'hosts':['example.org'], 'detail_limit':6}
        visited={i['url'] for day in range(34) for i in detail_batch(items,src,day)}
        self.assertEqual(len(visited),34)
        self.assertEqual(len(detail_batch(items,src,0)),6)
    def test_no_external_detail_fetch(self):
        items=[{'url':'https://elsewhere.org/a'}, {'url':'https://example.org/a.pdf'}]
        self.assertEqual(detail_batch(items,{'hosts':['example.org']}),[])
    def test_empty_page_is_error(self):
        with self.assertRaises(CheckError): page_evidence('<script>content()</script>')
