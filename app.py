import json
import sqlite3
from collections import Counter, defaultdict
from functools import partial
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from chatgpt_exchange import PRIORITY_SCORES, PROMPT, REVIEW_FIELDS, export_jobs, parse_reviews, review_priority
from job_engine import (
    DISCOVERY_TERMS, TRACKS, compare_profile, connect, diagnostic_url_key, fetch_arbeitnow,
    fetch_jobindex, fetch_page, fetch_remotive, fetch_rss, geography, save_job, score,
)

SEARCH_PROVIDERS = {
    'Jobindex': fetch_jobindex,
}
DEFAULT_SEARCH_TERMS = 'analytiker, finans, forretningsudvikler, data scientist, softwareudvikler'

st.set_page_config(page_title='Min jobsøgemaskine', page_icon='🔎', layout='wide')
st.title('🔎 Min jobsøgemaskine')
st.caption('Personlig jobfinder · Odense, Fyn, Middelfart og Aarhus tæt på Hovedbanegården · data gemmes lokalt på din Mac')
db = connect()

def setting(key, default):
    row = db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return json.loads(row['value']) if row else default

def put_setting(key, value):
    db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))
    db.commit()


def show_chatgpt_review(review):
    with st.container(border=True):
        st.markdown('**ChatGPT-vurdering**')
        for key, label in REVIEW_FIELDS.items():
            if review.get(key):
                st.markdown(f'**{label}**')
                st.write(review[key])

with st.sidebar:
    st.header('Din søgeprofil')
    previous_terms = setting('search_terms_v2', setting('search_terms', setting('jobnet_queries', DEFAULT_SEARCH_TERMS)))
    expanded_terms = ', '.join(dict.fromkeys(
        [term.strip() for term in previous_terms.split(',') if term.strip()] + list(DISCOVERY_TERMS)
    )) if previous_terms.strip() else ''
    search_terms = st.text_input(
        'Søgeord (adskilt med komma)',
        value=setting('search_terms_v3', expanded_terms),
        help='Alle forskellige søgeudtryk bruges i søgningen. Et tomt felt giver en bred søgning.',
    )
    with st.expander('Erfaring og karriereønsker'):
        experience = st.text_area(
            'Erfaring og kompetencer', value=setting('experience', ''),
            help='Skriv én konkret kompetence eller erfaring pr. linje, fx SQL, modelvalidering eller projektledelse.',
        )
        wishes = st.text_area(
            'Karriereønsker', value=setting('career_wishes', ''),
            help='Skriv ét ønske pr. linje, fx personaleansvar, hjemmearbejde eller Odense.',
        )
    weights = {}
    default_weights = {'Kvantitativ finans':4,'Rådgivning og forretning':5,'Data og software':3,'Andre brancher':3}
    for track in TRACKS:
        weights[track] = st.slider(track,0,5,int(setting('weight_'+track,default_weights[track])))
    minimum = st.slider(
        'Minimum matchscore', 0, 100, int(setting('minimum', 0)), 5,
        help='Filteret bruger ChatGPT-karakteren, når en vurdering har en tydelig prioritet. Ellers bruges den lokale score.',
    )
    show_rejected = st.checkbox('Vis afviste job',False)
    if st.button('Gem søgeprofil',use_container_width=True):
        for k,v in weights.items(): put_setting('weight_'+k,v)
        put_setting('minimum',minimum)
        put_setting('search_terms_v3', search_terms)
        put_setting('experience', experience)
        put_setting('career_wishes', wishes)
        st.success('Søgeprofil gemt')
    st.info('Aarhus-job markeres til kontrol af gangafstand til Aarhus H, hvis opslaget kun angiver byen. Appen beregner endnu ikke faktisk rejsetid eller afstand.')
    st.caption('Scoren rangerer opslag efter karrierespor og geografi. Profilanalysen viser tekstfund for din erfaring og dine ønsker.')

search_tab, results_tab, history_tab = st.tabs(['Find nye job','Joboversigt','Historik og eksport'])
with search_tab:
    st.subheader('Søg i åbne jobkilder')
    st.write(f"Henter opslag fra {', '.join(SEARCH_PROVIDERS)} med søgeordene i din søgeprofil.")
    with st.expander('Kilder og dækning', expanded=True):
        st.write('**Jobindex** · Portalens publicerede RSS-søgeresultater. Dækningen følger feedet for hvert søgeudtryk.')
        st.write('**Jobnet** · Ingen aktiv søgning. STARs officielle integration kræver en tilslutningsaftale.')
        st.write('**HR Manager / Talentech** · Ingen direkte søgning. Jobportal-API’et bruger et arbejdsgiveralias. Opslag, der også er på Jobindex, kan findes gennem Jobindex-feedet.')
        st.write('**Arbeitnow og Remotive** · Valgfrie internationale kilder. Egne RSS-feeds er også valgfrie.')
    c1,c2 = st.columns(2)
    use_arbeit = c1.checkbox('Arbeitnow (international)',False)
    use_remotive = c2.checkbox('Remotive (international)',False)
    rss = st.text_area('RSS-feed-adresser (én pr. linje)',value='\n'.join(setting('rss',[])),placeholder='https://eksempel.dk/jobs.rss')
    if st.button('🔎 Find nye job',type='primary'):
        feeds = [x.strip() for x in rss.splitlines() if x.strip()]
        put_setting('rss',feeds)
        put_setting('search_terms_v3', search_terms)
        queries = list(dict.fromkeys(term.strip() for term in search_terms.split(',') if term.strip()))
        sources = [
            (name, query, partial(fetch, query), False)
            for name, fetch in SEARCH_PROVIDERS.items()
            for query in queries or ['']
        ]
        if use_arbeit:
            sources.append(('Arbeitnow', '', fetch_arbeitnow, True))
        if use_remotive:
            sources.append(('Remotive', '', fetch_remotive, True))
        sources += [(url, '', partial(fetch_rss, url), True) for url in dict.fromkeys(feeds)]
        terms = [query.casefold() for query in queries]
        stats = defaultdict(Counter)
        errors = []
        query_report = []
        returned_jobs = []
        with st.spinner('Henter stillinger...'):
            for name, query, fetch, filter_locally in sources:
                counts = stats[name]
                query_row = {'Kilde': name, 'Søgeudtryk': query or '—', 'Hentet': None, 'Resultat': 'Gennemført'}
                query_report.append(query_row)
                try:
                    jobs = list(fetch())
                    query_row['Hentet'] = len(jobs)
                    counts['Hentet'] += len(jobs)
                    valid_jobs = []
                    for job in jobs:
                        if not job.get('title') or not job.get('url'):
                            counts['Mangler titel eller gyldigt link'] += 1
                        elif filter_locally and terms and not any(
                            term in f"{job['title']} {job.get('description', '')}".casefold() for term in terms
                        ):
                            counts['Ingen søgeord fundet'] += 1
                            returned_jobs.append((name, query, job['title'], job['url'], 'Frasorteret af søgeordsfilter'))
                        else:
                            valid_jobs.append(job)
                    try:
                        with db:
                            saved = [(job, save_job(db, job)) for job in valid_jobs]
                    except Exception:
                        counts['Kunne ikke gemmes'] += len(valid_jobs)
                        returned_jobs.extend((name, query, job['title'], job['url'], 'Kunne ikke gemmes')
                                             for job in valid_jobs)
                        raise
                    inserted = sum(result for _, result in saved)
                    returned_jobs.extend(
                        (name, query, job['title'], job['url'], 'Gemt' if result else 'Allerede gemt')
                        for job, result in saved
                    )
                    counts['Nye gemt'] += inserted
                    counts['Allerede gemt / dublet'] += len(valid_jobs) - inserted
                except Exception as exc:
                    counts['Fejl'] += 1
                    query_row['Resultat'] = 'Fejl'
                    label = f'{name} ({query})' if query else name
                    errors.append(f'{label}: {exc}')
        st.session_state['source_report'] = (dict(stats), errors)
        st.session_state['query_report'] = query_report
        st.session_state['returned_jobs'] = returned_jobs
    if 'source_report' in st.session_state:
        stats, errors = st.session_state['source_report']
        st.subheader('Seneste søgning pr. kilde')
        st.caption('Hentet tæller alle svar fra kilden. Samme opslag kan optræde i flere søgninger.')
        reasons = ('Mangler titel eller gyldigt link', 'Ingen søgeord fundet',
                   'Allerede gemt / dublet', 'Kunne ikke gemmes')
        st.dataframe(pd.DataFrame([
            {'Kilde': name, 'Hentet': counts['Hentet'], 'Nye gemt': counts['Nye gemt'],
             'Frasorteret': sum(counts[reason] for reason in reasons),
             **{reason: counts[reason] for reason in reasons}, 'Fejl': counts['Fejl']}
            for name, counts in stats.items()
        ]), hide_index=True)
        for error in errors:
            st.warning(error)
        with st.expander('Se hvert søgeudtryk'):
            st.dataframe(pd.DataFrame(st.session_state.get('query_report', [])), hide_index=True)
    st.divider()
    st.subheader('Tilføj et konkret jobopslag')
    with st.form('manual'):
        url = st.text_input('Link til jobopslaget')
        title = st.text_input('Stilling (valgfrit – kan rettes hvis siden ikke kan læses)')
        company = st.text_input('Virksomhed (valgfrit)')
        location = st.text_input('Arbejdssted (valgfrit)')
        description = st.text_area('Indsæt jobtekst (anbefales ved sider der blokerer automatisk læsning)')
        submitted = st.form_submit_button('Gem job')
    if submitted:
        try:
            job = fetch_page(url) if url and not description else {'title':title,'company':company,'location':location,'url':url,'description':description,'source':'Manuelt indsat','published':''}
            if title: job['title']=title
            if company: job['company']=company
            if location: job['location']=location
            if not job.get('title') or not job.get('url'): raise ValueError('Stilling og link skal udfyldes')
            changed=save_job(db,job); db.commit()
            st.success('Job gemt' if changed else 'Jobbet findes allerede')
        except Exception as exc: st.error(f'Kunne ikke tilføje jobbet: {exc}')

rows = [dict(x) for x in db.execute('SELECT * FROM jobs ORDER BY added DESC').fetchall()]
for job in rows:
    job['match'],job['why']=score(job,weights)

with results_tab:
    st.subheader('ChatGPT-vurdering af nye job')
    if rows:
        with st.expander('Eksportér job og importér ChatGPTs svar', expanded=True):
            export_section = st.container()
            st.code(PROMPT, language=None)
            review_file = st.file_uploader('JSON-fil med vurderinger fra ChatGPT', type=['json'])
            if review_file is not None:
                st.caption(f'Fil klar til import: {review_file.name}')
            if st.button('Importér ChatGPT-vurderinger'):
                st.session_state.pop('chatgpt_import_result', None)
                try:
                    if review_file is None:
                        raise ValueError('Vælg først svarfilen fra ChatGPT.')
                    reviews = parse_reviews(review_file.getvalue(), {job['id'] for job in rows})
                    with db:
                        db.executemany(
                            'INSERT INTO settings(key,value) VALUES(?,?) '
                            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                            [(f'chatgpt_review_{job_id}', json.dumps(review, ensure_ascii=False))
                             for job_id, review in reviews.items()],
                        )
                except (ValueError, UnicodeError) as exc:
                    st.session_state['chatgpt_import_result'] = ('error', str(exc))
                except sqlite3.Error as exc:
                    st.session_state['chatgpt_import_result'] = ('error', f'Kunne ikke gemme i databasen. {exc}')
                else:
                    st.session_state['chatgpt_import_result'] = ('success', f'Import færdig. Vurderinger gemt for {len(reviews)} job.')
                    st.session_state['chatgpt_review_selection'] = next(iter(reviews))
            if result := st.session_state.get('chatgpt_import_result'):
                if result[0] == 'error':
                    st.error(result[1])
                else:
                    st.success(result[1])
    else:
        st.caption('Hent eller tilføj job for at eksportere dem til ChatGPT.')
    chatgpt_reviews = {
        row['key'].removeprefix('chatgpt_review_'): json.loads(row['value'])
        for row in db.execute("SELECT key, value FROM settings WHERE key GLOB 'chatgpt_review_*'")
    }
    for job in rows:
        if review := chatgpt_reviews.get(job['id']):
            if job['status'] == 'Ny':
                job['status'] = 'Vurderet'
            if priority := review_priority(review):
                job['local_match'] = job['match']
                job['match'] = PRIORITY_SCORES[priority]
                job['review_priority'] = priority
    if rows:
        exportable = [job for job in rows if job['status'] == 'Ny' and job['id'] not in chatgpt_reviews]
        with export_section:
            st.caption('Eksporten omfatter job med status Ny, som endnu ikke har en ChatGPT-vurdering.')
            if exportable:
                st.download_button(
                    f'Download nye job til ChatGPT ({len(exportable)})', export_jobs(exportable),
                    file_name='jobopslag-til-chatgpt.json', mime='application/json',
                )
            else:
                st.info('Der er ingen nye job uden ChatGPT-vurdering at eksportere.')
    if chatgpt_reviews:
        assessed = {job['id']: job for job in rows if job['id'] in chatgpt_reviews}
        st.caption(f'{len(assessed)} af {len(rows)} gemte job har en ChatGPT-vurdering.')
        selected_review = st.selectbox(
            'Læs en gemt ChatGPT-vurdering', [None, *assessed],
            key='chatgpt_review_selection',
            format_func=lambda job_id: (
                f'{assessed[job_id]["title"]} · {assessed[job_id]["source"]}' if job_id else 'Vælg et job'
            ),
        )
        if selected_review:
            show_chatgpt_review(chatgpt_reviews[selected_review])
    st.divider()
    st.subheader('Ansøgningssamtale')
    conversation_jobs = {job['id']: job for job in rows}

    def conversation_job_label(job_id):
        if job_id is None:
            return 'Vælg et gemt job'
        job = conversation_jobs[job_id]
        return f'{job["title"]} · {job["company"]} · {job["source"]}'

    conversation_job = st.selectbox(
        'Job til samtalen', [None, *conversation_jobs], format_func=conversation_job_label,
    )
    conversation_key = f'conversation_{conversation_job}'
    conversation = setting(conversation_key, {}) if conversation_job else {}
    with st.form(conversation_key):
        conversation_url = st.text_input(
            'Link til ChatGPT-samtalen', value=conversation.get('url', ''),
            placeholder='https://chatgpt.com/…', disabled=conversation_job is None,
        )
        excerpts = st.text_area(
            'Uddrag fra samtalen (valgfrit)', value=conversation.get('excerpts', ''),
            help='Jobanalysen bruger de uddrag, du indsætter her.',
            disabled=conversation_job is None,
        )
        if st.form_submit_button('Gem samtale', disabled=conversation_job is None):
            url = conversation_url.strip()
            try:
                parsed = urlparse(url)
                valid = not url or (parsed.scheme == 'https' and bool(parsed.hostname))
            except ValueError:
                valid = False
            if valid:
                conversation = {'url': url, 'excerpts': excerpts.strip()}
                put_setting(conversation_key, conversation)
                st.success('Samtale gemt')
            else:
                st.error('Angiv et gyldigt link, der starter med https://.')
    if conversation.get('url'):
        st.link_button('Åbn ChatGPT-samtalen', conversation['url'])
    st.divider()
    st.subheader('Relevante stillinger')
    query = st.text_input('Filtrér efter titel, virksomhed eller arbejdssted')
    statuses = ['Ny', 'Vurderet', 'Interessant', 'Ansøgt', 'Afvist']
    status_filter = st.multiselect('Status', statuses, default=statuses if show_rejected else statuses[:-1])
    source_filter = st.selectbox('Kilde', [None, *sorted({j['source'] for j in rows if j['source']})],
                                 format_func=lambda source: source or 'Alle kilder')
    only_dk = st.checkbox(
        'Filtrér på arbejdssted',
        help='Vis kun opslag fra de prioriterede områder eller opslag med Danmark eller hjemmearbejde i arbejdsstedet.',
    )
    filtered = []
    excluded = {}
    display_stats = defaultdict(Counter)
    for job in rows:
        counts = display_stats[job['source'] or 'Ukendt']
        counts['Gemt'] += 1
        if source_filter is not None and job['source'] != source_filter:
            reason = 'Kildefilter'
        elif only_dk and geography(job['location'])[0] < 45:
            reason = 'Arbejdssted'
        elif job['match'] < minimum:
            reason = 'Matchscore'
        elif job['status'] not in status_filter:
            reason = 'Status'
        elif query.casefold() not in f"{job['title']} {job['company']} {job['location']}".casefold():
            reason = 'Fritekst'
        else:
            counts['Matcher'] += 1
            filtered.append(job)
            continue
        counts[reason] += 1
        excluded[job['id']] = reason
    filtered.sort(key=lambda x:x['match'],reverse=True)
    unique_jobs = []
    displayed_urls = set()
    for job in filtered:
        url = job['url']
        if url and url in displayed_urls:
            counts = display_stats[job['source'] or 'Ukendt']
            counts['Matcher'] -= 1
            counts['Samme joblink'] += 1
            excluded[job['id']] = 'Samme joblink'
        else:
            unique_jobs.append(job)
            if url:
                displayed_urls.add(url)
    filtered = unique_jobs
    st.caption(f'{len(filtered)} stillinger matcher dine filtre · {len(rows)} i databasen')
    if rows:
        with st.expander('Joboversigtens filtre pr. kilde'):
            st.caption('Hvert skjult opslag tælles under det første filter, det ikke passerer.')
            st.dataframe(pd.DataFrame([
                {'Kilde': name, 'Gemt': counts['Gemt'], 'Matcher': counts['Matcher'],
                 'Frasorteret': counts['Gemt'] - counts['Matcher'],
                 **{reason: counts[reason] for reason in ('Kildefilter', 'Arbejdssted', 'Matchscore', 'Status', 'Fritekst', 'Samme joblink')}}
                for name, counts in sorted(display_stats.items())
            ]), hide_index=True)
    page_size = 50
    with st.expander('Fejlsøg et bestemt opslag'):
        lookup = st.text_input('Opslagets URL eller en del af titlen').strip()
        if lookup:
            is_url = lookup.startswith(('https://', 'http://'))
            lookup_key = diagnostic_url_key(lookup)

            def matches_lookup(title, url):
                if is_url:
                    return diagnostic_url_key(url or '') == lookup_key
                return lookup.casefold() in (title or '').casefold()

            positions = {job['id']: index for index, job in enumerate(filtered)}
            saved_hits = [job for job in rows if matches_lookup(job['title'], job['url'])]
            returned = [
                entry for entry in st.session_state.get('returned_jobs', [])
                if matches_lookup(entry[2], entry[3])
            ]
            if isinstance(lookup_key, tuple) and lookup_key[0] == 'HR Manager':
                st.info('HR Manager søges ikke direkte. Søg på opslagets titel her for at finde en eventuel Jobindex-version.')
            for job in saved_hits:
                reason = excluded.get(job['id'])
                visibility = f'Skjult af {reason.lower()}' if reason else f'Vises på resultatside {positions[job["id"]] // page_size + 1}'
                st.write(f'**{job["title"]}** · {job["source"]} · {visibility} · {job["match"]}/100 (minimum {minimum})')
                st.caption(f'{job["location"] or "Arbejdssted ikke angivet"} · {job["why"]}')
            if returned:
                st.dataframe(pd.DataFrame(returned, columns=['Kilde', 'Søgeudtryk', 'Titel', 'URL', 'Import']),
                             hide_index=True, column_order=['Kilde', 'Søgeudtryk', 'Titel', 'Import'])
            elif 'returned_jobs' not in st.session_state:
                st.info('Kør en søgning for at få oplysninger om, hvad kilderne returnerer.')
            elif not saved_hits:
                st.info('Ingen gemte opslag eller identificerbare svar fra seneste søgning matcher. Se søgeudtryk og kildefejl under Find nye job. Feedet viser et udsnit af portalens opslag.')
            else:
                st.caption('Opslaget var ikke blandt de identificerbare svar fra seneste søgning.')
    page = 1
    if len(filtered) > page_size:
        page_count = (len(filtered) + page_size - 1) // page_size
        page = st.selectbox(
            'Resultatside', range(1, page_count + 1),
            format_func=lambda number: f'Side {number} af {page_count}',
        )
        start = (page - 1) * page_size + 1
        end = min(page * page_size, len(filtered))
        st.caption(f'Viser job {start}–{end} af {len(filtered)}, sorteret efter matchscore. Brug titelfilteret til at finde et bestemt opslag på tværs af siderne.')
    if not filtered and rows:
        st.info('Prøv at sænke minimum matchscore eller at ændre filtrene.')
    for j in filtered[(page - 1) * page_size:page * page_size]:
        rating = f"{j['match']} / 100"
        if priority := j.get('review_priority'):
            rating += f' · ChatGPT: {priority} prioritet'
        with st.expander(f"{rating} · {j['title']} · {j['company']} ({j['status']})"):
            st.write(f"**Sted:** {j['location'] or 'Ikke angivet'} · **Kilde:** {j['source']}")
            st.markdown(f"[Åbn jobopslag]({j['url']})")
            if review := chatgpt_reviews.get(j['id']):
                show_chatgpt_review(review)
            if priority:
                st.caption(f"ChatGPT-prioriteten giver {j['match']}/100 i sortering og filter. Lokal nøgleordsscore: {j['local_match']}/100.")
            conversation = setting('conversation_' + j['id'], {})
            st.write(j['why'])
            first_status = 'Vurderet' if j['id'] in chatgpt_reviews else 'Ny'
            job_statuses = [first_status, *statuses[2:]]
            new_status = st.selectbox(
                'Status', job_statuses, index=job_statuses.index(j['status']), key='status_'+j['id'],
            )
            notes = st.text_area('Dine noter',value=j['notes'] or '',key='notes_'+j['id'])
            if st.button('Gem vurdering',key='save_'+j['id']):
                stored_status = 'Ny' if new_status == 'Vurderet' else new_status
                db.execute('UPDATE jobs SET status=?,notes=? WHERE id=?',(stored_status,notes,j['id']))
                db.commit(); st.success('Gemt. Opdatér siden for at opdatere filtreringen.')
            with st.popover('Vis jobtekst'):
                st.text(j['description'] or 'Ingen jobtekst')
            with st.popover('Analysér opslag'):
                text_key = 'analysis_text_' + j['id']
                if j['source'] == 'Jobindex':
                    st.caption('Jobindex kan levere et uddrag. Hent teksten fra annoncen eller indsæt hele opslaget.')
                if j['url'] and st.button('Hent tekst fra annoncen', key='fetch_text_' + j['id']):
                    try:
                        fetched = fetch_page(j['url'])['description']
                        if not fetched.strip():
                            raise ValueError('Siden returnerede ingen jobtekst.')
                        st.session_state[text_key] = fetched
                    except (ValueError, OSError) as exc:
                        st.warning(f'Kunne ikke hente teksten. Du kan indsætte den nedenfor. {exc}')
                st.session_state.setdefault(text_key, j['description'] or '')
                analysis_text = st.text_area(
                    'Jobtekst til analyse', key=text_key,
                    help='Du kan erstatte teksten med hele opslaget, hvis kilden kun leverer et uddrag.',
                )
                conversation_excerpts = conversation.get('excerpts', '')
                if not any(value.strip() for value in (experience, wishes, conversation_excerpts)):
                    st.info('Udfyld din søgeprofil eller tilføj et uddrag under Ansøgningssamtale.')
                elif not analysis_text.strip():
                    st.info('Hent eller indsæt jobteksten for at få en analyse.')
                else:
                    st.caption('Tekstfund viser, hvad opslaget omtaler. Læs citaterne for at se, om der er tale om et krav eller et tilbud.')
                    for label, criteria in [
                        ('Din erfaring', experience),
                        ('Dine karriereønsker', wishes),
                        ('Fra din ansøgningssamtale', conversation_excerpts),
                    ]:
                        if not criteria.strip():
                            continue
                        st.markdown(f'**{label}**')
                        matched, unclear = compare_profile({**j, 'description': analysis_text}, criteria)
                        for criterion, excerpt in matched:
                            st.text(f'{criterion} — {excerpt}')
                        if unclear:
                            st.text('Skal afklares: ' + ', '.join(unclear))

with history_tab:
    st.subheader('Alle gemte stillinger')
    if rows:
        df = pd.DataFrame([{'Match':j['match'],'Stilling':j['title'],'Virksomhed':j['company'],'Sted':j['location'],'Status':j['status'],'Kilde':j['source'],'Link':j['url'],'Noter':j['notes']} for j in rows])
        st.dataframe(df,use_container_width=True,hide_index=True)
        st.download_button('Download historik som CSV',df.to_csv(index=False).encode('utf-8-sig'),'jobhistorik.csv','text/csv')
    else:
        st.write('Ingen job endnu. Start en søgning under “Find nye job”.')
    st.divider()
    st.subheader('Registrér tidligere ansøgninger')
    st.write('Brug denne formular til at registrere job, du allerede har søgt, så de ikke fremstår som nye.')
    with st.form('past'):
        past_title = st.text_input('Tidligere stilling')
        past_company = st.text_input('Virksomhed')
        past_url = st.text_input('Joblink (valgfrit)')
        past_status = st.selectbox('Status',['Ansøgt','Afvist','Interessant'])
        if st.form_submit_button('Registrér'):
            if not past_title or not past_company: st.error('Udfyld stilling og virksomhed')
            else:
                job={'title':past_title,'company':past_company,'url':past_url,'description':'','source':'Tidligere ansøgning'}
                from job_engine import make_id
                save_job(db,job)
                db.execute('UPDATE jobs SET status=? WHERE id=?',(past_status,make_id(past_url,past_title,past_company)))
                db.commit(); st.success('Registreret')
