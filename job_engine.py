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
    job['id'] = make_id(job.get('url'), job.get('title', ''), job.get('company', ''))
    db.execute('''INSERT OR IGNORE INTO jobs (id,title,company,location,url,description,source,published,added) VALUES (?,?,?,?,?,?,?,?,?)''', (
        job['id'], job.get('title',''), job.get('company',''), job.get('location',''), job.get('url',''), job.get('description',''), job.get('source',''), job.get('published',''), datetime.now(timezone.utc).isoformat()))
    return db.execute('SELECT changes()').fetchone()[0]


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
        yield {
            'title': (ad.get('title') or '').strip(),
            'company': ad.get('hiringOrgName') or '',
            'location': ', '.join(place for place in places if place),
            'url': f'https://jobnet.dk/find-job/{ad_id}',
            'description': clean_html(ad.get('description')),
            'source': 'Jobnet',
            'published': ad.get('publicationDate') or '',
        }


def fetch_arbeitnow():
    r = requests.get('https://www.arbeitnow.com/api/job-board-api', headers=HEADERS, timeout=18)
    r.raise_for_status()
    for item in r.json().get('data', []):
        yield {'title':item.get('title',''), 'company':item.get('company_name',''), 'location':item.get('location',''), 'url':item.get('url',''), 'description':clean_html(item.get('description','')), 'source':'Arbeitnow', 'published':str(item.get('created_at',''))}


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
    return {'title':title[:240], 'company':parsed.hostname, 'location':'', 'url':url, 'description':soup.get_text(' ',strip=True)[:40000], 'source':'Manuelt link', 'published':''}


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
    body = (job['description'] or '').lower()[:25000]
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
