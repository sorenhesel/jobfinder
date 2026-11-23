import json
from functools import partial
from urllib.parse import urlparse

import pandas as pd
import streamlit as st
from job_engine import (
    TRACKS, compare_profile, connect, fetch_arbeitnow, fetch_jobindex, fetch_jobnet, fetch_page, fetch_remotive,
    fetch_rss, save_job, score,
)

SEARCH_PROVIDERS = {
    'Jobnet': fetch_jobnet,
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

with st.sidebar:
    st.header('Din søgeprofil')
    search_terms = st.text_input(
        'Søgeord (adskilt med komma)',
        value=setting('search_terms', setting('jobnet_queries', DEFAULT_SEARCH_TERMS)),
        help='De første fem forskellige søgeudtryk bruges på alle kilder. Et tomt felt giver en bred søgning.',
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
    minimum = st.slider('Minimum matchscore',0,100,int(setting('minimum',0)),5)
    show_rejected = st.checkbox('Vis afviste job',False)
    if st.button('Gem søgeprofil',use_container_width=True):
        for k,v in weights.items(): put_setting('weight_'+k,v)
        put_setting('minimum',minimum)
        put_setting('search_terms', search_terms)
        put_setting('experience', experience)
        put_setting('career_wishes', wishes)
        st.success('Søgeprofil gemt')
    st.info('Aarhus-job markeres til kontrol af gangafstand til Aarhus H, hvis opslaget kun angiver byen. Appen beregner endnu ikke faktisk rejsetid eller afstand.')
    st.caption('Scoren rangerer opslag efter karrierespor og geografi. Profilanalysen viser tekstfund for din erfaring og dine ønsker.')

search_tab, results_tab, history_tab = st.tabs(['Find nye job','Joboversigt','Historik og eksport'])
with search_tab:
    st.subheader('Søg i åbne jobkilder')
    st.write(f"Henter opslag fra {', '.join(SEARCH_PROVIDERS)} med søgeordene i din søgeprofil.")
    c1,c2 = st.columns(2)
    use_arbeit = c1.checkbox('Arbeitnow (international)',False)
    use_remotive = c2.checkbox('Remotive (international)',False)
    rss = st.text_area('RSS-feed-adresser (én pr. linje)',value='\n'.join(setting('rss',[])),placeholder='https://eksempel.dk/jobs.rss')
    if st.button('🔎 Find nye job',type='primary'):
        feeds = [x.strip() for x in rss.splitlines() if x.strip()]
        put_setting('rss',feeds)
        put_setting('search_terms', search_terms)
        queries = list(dict.fromkeys(term.strip() for term in search_terms.split(',') if term.strip()))[:5]
        sources = [
            (f'{name} ({query})' if query else name, partial(fetch, query), False)
            for name, fetch in SEARCH_PROVIDERS.items()
            for query in queries or ['']
        ]
        if use_arbeit:
            sources.append(('Arbeitnow', fetch_arbeitnow, True))
        if use_remotive:
            sources.append(('Remotive', fetch_remotive, True))
        sources += [(url, partial(fetch_rss, url), True) for url in feeds]
        terms = [query.casefold() for query in queries]
        added=0; seen=0; errors=[]
        with st.spinner('Henter stillinger...'):
            for name, fetch, filter_locally in sources:
                try:
                    jobs = [job for job in fetch() if job.get('title') and job.get('url')]
                    if filter_locally and terms:
                        jobs = [
                            job for job in jobs
                            if any(term in f"{job['title']} {job['description']}".casefold() for term in terms)
                        ]
                    with db:
                        inserted = sum(save_job(db, job) for job in jobs)
                    seen += len(jobs)
                    added += inserted
                except Exception as exc:
                    errors.append(f'{name}: {exc}')
        report = f'Gennemgået {seen} opslag. {added} nye job gemt.'
        if len(errors) == len(sources):
            st.error('Ingen jobkilder kunne hentes.')
        elif errors:
            st.warning(report)
        else:
            st.success(report)
        if seen:
            st.caption('Se resultaterne under Joboversigt, eller se alle gemte opslag under Historik og eksport.')
        for error in errors: st.warning(error)
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
    st.subheader('Relevante stillinger')
    query = st.text_input('Filtrér efter titel, virksomhed eller arbejdssted')
    status_filter = st.multiselect('Status', ['Ny','Interessant','Ansøgt','Afvist'],default=['Ny','Interessant','Ansøgt'] if not show_rejected else ['Ny','Interessant','Ansøgt','Afvist'])
    source_filter = st.selectbox('Kilde', [None, *sorted({j['source'] for j in rows if j['source']})],
                                 format_func=lambda source: source or 'Alle kilder')
    only_dk = st.checkbox(
        'Filtrér på arbejdssted',
        help='Vis kun opslag fra de prioriterede områder eller opslag med Danmark eller hjemmearbejde i arbejdsstedet.',
    )
    from job_engine import geography
    filtered = [
        j for j in rows
        if (source_filter is None or j['source'] == source_filter)
        and (not only_dk or geography(j['location'])[0] >= 45)
        and j['match'] >= minimum
        and j['status'] in status_filter
        and query.lower() in (j['title'] + ' ' + j['company'] + ' ' + j['location']).lower()
    ]
    filtered.sort(key=lambda x:x['match'],reverse=True)
    st.caption(f'{len(filtered)} stillinger matcher dine filtre · {len(rows)} i databasen')
    if len(filtered) > 150:
        st.caption('Viser de 150 højeste matchscore. Vælg en kilde eller filtrér for at indsnævre listen.')
    if not filtered and rows:
        st.info('Prøv at sænke minimum matchscore eller at ændre filtrene.')
    for j in filtered[:150]:
        with st.expander(f"{j['match']} / 100 · {j['title']} · {j['company']} ({j['status']})"):
            st.write(f"**Sted:** {j['location'] or 'Ikke angivet'} · **Kilde:** {j['source']}")
            st.write(j['why'])
            st.markdown(f"[Åbn jobopslag]({j['url']})")
            new_status = st.selectbox('Status',['Ny','Interessant','Ansøgt','Afvist'],index=['Ny','Interessant','Ansøgt','Afvist'].index(j['status']),key='status_'+j['id'])
            notes = st.text_area('Dine noter',value=j['notes'] or '',key='notes_'+j['id'])
            if st.button('Gem vurdering',key='save_'+j['id']):
                db.execute('UPDATE jobs SET status=?,notes=? WHERE id=?',(new_status,notes,j['id']))
                db.commit(); st.success('Gemt. Opdatér siden for at opdatere filtreringen.')
            conversation_key = 'conversation_' + j['id']
            conversation = setting(conversation_key, {})
            with st.popover('Ansøgningssamtale'):
                with st.form(conversation_key):
                    conversation_url = st.text_input('Link til ChatGPT-samtalen', value=conversation.get('url', ''))
                    excerpts = st.text_area(
                        'Uddrag fra samtalen', value=conversation.get('excerpts', ''),
                        help='Indsæt de relevante uddrag. Skriv gerne én erfaring eller ét ønske pr. linje for at få tydeligere tekstfund.',
                    )
                    if st.form_submit_button('Gem samtale'):
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
