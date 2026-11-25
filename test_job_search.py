import tempfile
import unittest
from html import escape
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

import job_engine

HR_MANAGER_URL = (
    'https://candidate.hr-manager.net/ApplicationInit.aspx'
    '?cid=3010&ProjectId=173744&DepartmentId=19143&MediaId=5130'
)
CASE_JYSKE = {
    'query': 'kapitalmarkeder',
    'title': 'Forretningsudvikler med fokus på kapitalmarkeder, regulering, realkredit og IT',
    'company': 'Jyske Bank',
    'location': 'København V',
    'url': 'https://www.jobindex.dk/vis-job/h1718418',
    'description': 'Arbejd som forretningsudvikler mellem realkreditforretningen, kapitalmarkederne, regulering og IT.',
    'evidence': ('kapitalmarkeder', 'realkredit', 'regulering'),
}
CASE_SKAT = {
    'query': 'corporate finance',
    'title': 'Brænder du for corporate finance, økonomiske analyser eller finansiering?',
    'company': 'Skattestyrelsen',
    'location': 'København S',
    'url': 'https://www.jobindex.dk/vis-job/h1718572',
    'description': 'Undersøg beskatningsgrundlaget, udarbejd værdiansættelser af unoterede virksomheder '
                   'og lav regnskabsmæssige analyser af selskaber og industrier.',
    'evidence': ('værdiansættelse', 'økonomisk analyse', 'offentlig forvaltning'),
}
CASES = (CASE_JYSKE, CASE_SKAT)
WEIGHTS = dict(zip(job_engine.TRACKS, [4, 5, 3, 3]))


def response_for_query(url, *, params, **kwargs):
    if url != 'https://www.jobindex.dk/jobsoegning.rss':
        raise AssertionError(f'Uventet kilde: {url}')
    items = ''.join(
        f'<item><title>{escape(job["title"])}, {job["company"]}</title><link>{job["url"]}</link>'
        f'<description><![CDATA[<h4>{job["title"]}</h4><div class="jobad-element-area">'
        f'{job["location"]}</div><p>{job["description"]}</p>]]></description></item>'
        for job in CASES if job['query'] == params['q']
    )
    feed = f'<rss version="2.0"><channel><title>Jobindex</title>{items}</channel></rss>'
    return Mock(content=feed.encode())


class SourceRegressionTest(unittest.TestCase):
    @patch.object(job_engine.requests, 'get', side_effect=response_for_query)
    def test_jobindex_feed_reads_both_cross_posted_ads(self, request):
        for case in CASES:
            with self.subTest(company=case['company']):
                [job] = job_engine.fetch_jobindex(case['query'])
                for field in ('url', 'title', 'company', 'location', 'description'):
                    self.assertEqual(job[field], case[field])
                self.assertEqual(job['source'], 'Jobindex')
        self.assertEqual(request.call_count, 2)


class MatchingRegressionTest(unittest.TestCase):
    def test_fetched_ads_score_from_body_and_pass_location(self):
        for case in CASES:
            with self.subTest(company=case['company']):
                value, reason = job_engine.score(case, WEIGHTS)
                self.assertGreaterEqual(value, 45)
                self.assertIn('Fagligt overlap i jobteksten', reason)
                for evidence in case['evidence']:
                    self.assertIn(evidence, reason)
                self.assertGreaterEqual(job_engine.geography(case['location'])[0], 45)

    def test_neither_title_alone_nor_duplicated_rss_heading_is_strong_evidence(self):
        for case in CASES:
            with self.subTest(company=case['company']):
                for body in ('', f'{case["title"]} {case["location"]}'):
                    value, reason = job_engine.score({**case, 'description': body}, WEIGHTS)
                    self.assertLess(value, 20)
                    self.assertNotIn('Fagligt overlap i jobteksten', reason)


class DiagnosticsRegressionTest(unittest.TestCase):
    def test_discovery_and_saved_job_filter_are_reported_separately(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            job_engine, 'DB', Path(folder) / 'jobs.sqlite3'
        ), patch.object(job_engine.requests, 'get', side_effect=response_for_query) as request:
            with job_engine.connect() as db:
                db.execute('INSERT INTO settings VALUES (?, ?)', ('search_terms_v2', '"analytiker, finans"'))

            app = AppTest.from_file('app.py').run()
            next(button for button in app.button if button.label == '🔎 Find nye job').click().run()
            self.assertFalse(app.exception)
            queries = [call.kwargs['params']['q'] for call in request.call_args_list]
            self.assertTrue(set(job_engine.DISCOVERY_TERMS).issubset(queries))
            lookup = next(widget for widget in app.text_input if widget.label.startswith('Opslagets URL'))
            lookup.set_value(HR_MANAGER_URL).run()
            self.assertTrue(any('HR Manager søges ikke direkte' in item.value for item in app.info))

            next(widget for widget in app.text_input if widget.label.startswith('Opslagets URL')).set_value(
                'Brænder du for corporate finance'
            )
            next(widget for widget in app.slider if widget.label == 'Minimum matchscore').set_value(100).run()
            self.assertFalse(app.exception)
            self.assertTrue(any('Skjult af matchscore' in item.value for item in app.markdown))
            trace = next(table.value for table in app.dataframe if 'Import' in table.value)
            self.assertEqual(trace.loc[0, ['Kilde', 'Søgeudtryk', 'Import']].tolist(),
                             ['Jobindex', 'corporate finance', 'Gemt'])

            next(widget for widget in app.text_input if widget.label.startswith('Opslagets URL')).set_value(
                'https://www.jobindex.dk/jobannonce/h1718418/forretningsudvikler'
            ).run()
            trace = next(table.value for table in app.dataframe if 'Import' in table.value)
            self.assertEqual(trace.loc[0, 'Titel'], CASE_JYSKE['title'])


if __name__ == '__main__':
    unittest.main()
