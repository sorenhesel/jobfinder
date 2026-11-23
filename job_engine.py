import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import feedparser
import requests
from bs4 import BeautifulSoup

DB = Path(__file__).with_name('jobs.sqlite3')
HEADERS = {'User-Agent': 'PersonalJobFinder/1.0 (personal job discovery)'}

TRACKS = {
    'Kvantitativ finans': ['quantitative analyst', 'quant analyst', 'quantitative', 'model validation', 'model risk', 'risk modelling', 'risk modeling', 'pricing', 'valuation', 'stress testing', 'financial modelling', 'finansielle modeller', 'risikomodeller', 'modelvalidering', 'aktuar'],
    'Rådgivning og forretning': ['financial advisory', 'financial analyst', 'business development', 'forretningsudvikling', 'forretningsudvikler', 'rådgivning', 'advisory', 'business analyst', 'investment analyst', 'konsulent', 'consultant', 'corporate finance', 'm&a', 'finansiel analyse'],
    'Data og software': ['data analyst', 'data scientist', 'analytics', 'software developer', 'software engineer', 'python', 'c++', 'c#', 'automation', 'automatisering', 'sql', 'data engineer', 'application developer'],
    'Andre brancher': ['energy', 'energi', 'insurance', 'forsikring', 'pension', 'pension', 'utilities', 'treasury', 'fintech', 'banking', 'bank', 'financial services'],
}
SKILLS = ['quantitative', 'mathematical', 'matematisk', 'financial', 'finansiel', 'risk', 'risiko', 'pricing', 'valuation', 'modellering', 'modelling', 'modeling', 'data analysis', 'dataanalyse', 'python', 'c++', 'c#', 'sql', 'stakeholder', 'automation', 'automatisering', 'stress test', 'database', 'software', 'statistics', 'statistik']
NEGATIVE = ['graduate program', 'student assistant', 'internship', 'praktikant', 'studentermedhjælper', 'phd student']


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, url TEXT, description TEXT, source TEXT, published TEXT, added TEXT, status TEXT DEFAULT 'Ny', notes TEXT DEFAULT '')''')
    db.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    db.commit()
    return db


def clean_html(html):
    return BeautifulSoup(html or '', 'html.parser').get_text(' ', strip=True)


def make_id(url, title, company):
    return hashlib.sha256((url or (title + '|' + company)).strip().lower().encode()).hexdigest()[:24]


def save_job(db, job):
    job['id'] = make_id(job.get('identity_url') or job.get('url'), job.get('title', ''), job.get('company', ''))
    db.execute('''INSERT OR IGNORE INTO jobs (id,title,company,location,url,description,source,published,added) VALUES (?,?,?,?,?,?,?,?,?)''', (
        job['id'], job.get('title',''), job.get('company',''), job.get('location',''), job.get('url',''), job.get('description',''), job.get('source',''), job.get('published',''), datetime.now(timezone.utc).isoformat()))
    inserted = db.execute('SELECT changes()').fetchone()[0]
    if not inserted and job.get('identity_url') and job['url'] != job['identity_url']:
        db.execute(
            "UPDATE jobs SET url = ? WHERE id = ? AND source = 'Jobnet' AND url <> ?",
            (job['url'], job['id'], job['url']),
        )
    return inserted


def fetch_jobnet(query):
    response = requests.get(
        'https://jobnet.dk/bff/FindJob/Search',
        headers={**HEADERS, 'x-csrf': '1'},
        params={
            'searchString': query,
            'countries': 'DK',
            'resultsPerPage': 25,
            'pageNumber': 1,
            'orderType': 'BestMatch',
            'kmRadius': 50,
        },
        timeout=15,
    )
    response.raise_for_status()
    ads = response.json()['jobAds']
    if not isinstance(ads, list):
        raise ValueError('Jobnet returnerede et ukendt svarformat')
    for ad in ads:
        if (ad.get('country') or '').casefold() not in {'danmark', 'denmark', 'dk'}:
            continue
        try:
            ad_id = UUID(ad.get('jobAdId') or '')
        except ValueError:
            continue
        district = ' '.join(
            str(part) for part in (ad.get('postalCode'), ad.get('postalDistrictName')) if part
        )
        places = [
            (ad.get('workPlaceAddress') or '').strip(),
            district or (ad.get('municipality') or '').strip(),
            'Danmark',
        ]
        jobnet_url = f'https://jobnet.dk/find-job/{ad_id}'
        external_url = (ad.get('jobAdUrl') or '').strip()
        parsed_url = urlparse(external_url)
        use_external = ad.get('isExternal') and parsed_url.scheme in {'http', 'https'} and parsed_url.hostname
        yield {
            'title': (ad.get('title') or '').strip(),
            'company': ad.get('hiringOrgName') or '',
            'location': ', '.join(place for place in places if place),
            'url': external_url if use_external else jobnet_url,
            'identity_url': jobnet_url,
            'description': clean_html(ad.get('description')),
            'source': 'Jobnet',
            'published': ad.get('publicationDate') or '',
        }


def fetch_arbeitnow():
    r = requests.get('https://www.arbeitnow.com/api/job-board-api', headers=HEADERS, timeout=18)
    r.raise_for_status()
    for item in r.json().get('data', []):
        yield {'title':item.get('title',''), 'company':item.get('company_name',''), 'location':item.get('location',''), 'url':item.get('url',''), 'description':clean_html(item.get('description','')), 'source':'Arbeitnow', 'published':str(item.get('created_at',''))}


def fetch_jobindex(query):
    response = requests.get(
        'https://www.jobindex.dk/jobsoegning.rss',
        params={'q': query},
        headers=HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if feed.version != 'rss20' or (feed.bozo and not feed.entries):
        raise ValueError('Jobindex returnerede et ugyldigt RSS-feed')
    for item in feed.entries[:25]:
        url = urlparse(item.get('link', ''))
        if (url.scheme != 'https' or url.netloc != 'www.jobindex.dk'
                or not re.fullmatch(r'/vis-job/[^/]+', url.path)):
            continue
        body = BeautifulSoup(item.get('summary', ''), 'html.parser')
        heading = body.select_one('h4')
        area = body.select_one('.jobad-element-area, .jix_robotjob--area')
        title = heading.get_text(' ', strip=True) if heading else item.get('title', '')
        company = item.get('author', '')
        if not company and item.get('title', '').startswith(f'{title}, '):
            company = item['title'][len(title) + 2:]
        yield {
            'title': title,
            'company': company,
            'location': area.get_text(' ', strip=True) if area else '',
            'url': f'https://www.jobindex.dk{url.path}',
            'description': body.get_text(' ', strip=True),
            'source': 'Jobindex',
            'published': item.get('published', ''),
        }


def fetch_remotive():
    r = requests.get('https://remotive.com/api/remote-jobs', headers=HEADERS, timeout=18)
    r.raise_for_status()
    for item in r.json().get('jobs', []):
        yield {'title':item.get('title',''), 'company':item.get('company_name',''), 'location':item.get('candidate_required_location','Remote'), 'url':item.get('url',''), 'description':clean_html(item.get('description','')), 'source':'Remotive', 'published':item.get('publication_date','')}


def fetch_rss(url):
    r = requests.get(url, headers=HEADERS, timeout=18)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise ValueError('Feedet kunne ikke læses')
    for item in feed.entries[:200]:
        yield {'title':item.get('title',''), 'company':item.get('author',''), 'location':'', 'url':item.get('link',''), 'description':clean_html(item.get('summary','')), 'source':urlparse(url).netloc, 'published':item.get('published','')}


def fetch_page(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname:
        raise ValueError('Angiv en gyldig http(s)-adresse')
    r = requests.get(url, headers=HEADERS, timeout=18)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    title = (soup.find('h1').get_text(' ',strip=True) if soup.find('h1') else (soup.title.get_text(' ',strip=True) if soup.title else url))
    for el in soup(['script','style','nav','footer','header']): el.decompose()
    content = soup.select_one('main article, main, article') or soup
    return {'title':title[:240], 'company':parsed.hostname, 'location':'', 'url':url, 'description':content.get_text('\n',strip=True), 'source':'Manuelt link', 'published':''}


def compare_profile(job, criteria):
    """Find profile criteria and quote nearby text from the entire available posting."""
    text = '\n'.join(job.get(field) or '' for field in ('title', 'location', 'description'))
    text = re.sub(r'\s+', ' ', text).strip()
    matched, unclear = [], []
    seen = set()
    for line in criteria.splitlines():
        criterion = ' '.join(line.strip(' \t•-').split())
        if not criterion or criterion.casefold() in seen:
            continue
        seen.add(criterion.casefold())
        match = re.search(rf'(?<!\w){re.escape(criterion)}(?!\w)', text, re.IGNORECASE)
        if match is None:
            unclear.append(criterion)
            continue
        start = max(0, match.start() - 65)
        end = min(len(text), match.end() + 100)
        excerpt = ('…' if start else '') + text[start:end] + ('…' if end < len(text) else '')
        matched.append((criterion, excerpt))
    return matched, unclear


def geography(location):
    """Conservative geography classification; Aarhus requires station proximity verification."""
    loc = (location or '').casefold()
    if any(x in loc for x in ('middelfart', 'nørre aaby', 'nørre åby', 'ejby', 'gelsted', 'brenderup')):
        return 100, 'Middelfart-området'
    if any(x in loc for x in ('odense', 'fyn', 'svendborg', 'nyborg')):
        return 95, 'Fyn'
    if any(x in loc for x in ('aarhus', 'århus')):
        if any(x in loc for x in ('aarhus h', 'århus h', 'banegårdspladsen', 'aarhus hovedbanegård', 'århus hovedbanegård')):
            return 95, 'Aarhus H (kontrollér gangafstand)'
        return 45, 'Aarhus – afstand til banegården skal undersøges'
    if any(x in loc for x in ('københavn', 'copenhagen')):
        return 75, 'København – vurder hjemmearbejde'
    if any(x in loc for x in ('remote', 'denmark', 'danmark')):
        return 65, 'Arbejdssted/hjemmearbejde skal afklares'
    return (40, 'Arbejdssted ikke oplyst') if not loc else (10, 'Uden for prioriterede områder')


def score(job, weights):
    title = (job['title'] or '').lower()
    body = (job['description'] or '').lower()
    text = title + ' ' + body
    hits = {}
    for track, terms in TRACKS.items():
        count = sum(3 if term in title else 1 for term in terms if term in text)
        hits[track] = min(100, count * 14)
    skill_hits = [s for s in SKILLS if s in text]
    competence = min(100, len(skill_hits) * 10 + (20 if any(x in title for x in ('senior','lead','specialist','analyst','consultant','udvikler')) else 0))
    interest = sum(hits[k] * weights.get(k,0) for k in TRACKS) / max(1,sum(weights.values()))
    location = (job['location'] or '').lower()
    geo, geo_reason = geography(location)
    penalty = 35 if any(term in title for term in NEGATIVE) else 0
    total = round(max(0,min(100,0.45*competence + 0.45*interest + 0.10*geo - penalty)))
    top = sorted(hits,key=hits.get,reverse=True)[:2]
    explanation = 'Geografi: ' + geo_reason + '. Spor: ' + ', '.join(f'{t} ({hits[t]})' for t in top if hits[t]) + '. Kompetencer: ' + (', '.join(skill_hits[:8]) if skill_hits else 'få direkte nøgleord')
    return total, explanation
