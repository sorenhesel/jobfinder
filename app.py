import json
import pandas as pd
import streamlit as st
from job_engine import (
    TRACKS, connect, fetch_arbeitnow, fetch_jobnet, fetch_page, fetch_remotive,
    fetch_rss, save_job, score,
)

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
    weights = {}
    default_weights = {'Kvantitativ finans':4,'Rådgivning og forretning':5,'Data og software':3,'Andre brancher':3}
    for track in TRACKS:
        weights[track] = st.slider(track,0,5,int(setting('weight_'+track,default_weights[track])))
    minimum = st.slider('Minimum matchscore',0,100,int(setting('minimum',45)),5)
    show_rejected = st.checkbox('Vis afviste job',False)
    if st.button('Gem søgeprofil',use_container_width=True):
        for k,v in weights.items(): put_setting('weight_'+k,v)
        put_setting('minimum',minimum)
        st.success('Søgeprofil gemt')
    st.info('Aarhus-job markeres til kontrol af gangafstand til Aarhus H, hvis opslaget kun angiver byen. Appen beregner endnu ikke faktisk rejsetid eller afstand.')
    st.info('Scoren er en vejledende nøgleordsbaseret vurdering, ikke en AI-vurdering af hele jobopslaget.')

search_tab, results_tab, history_tab = st.tabs(['Find nye job','Joboversigt','Historik og eksport'])
with search_tab:
    st.subheader('Søg i åbne jobkilder')
    st.write('Hent danske jobopslag fra Jobnet direkte til Joboversigt.')
    jobnet_queries = st.text_input(
        'Søgeord på Jobnet (adskilt med komma)',
        value=setting('jobnet_queries', 'analytiker, finans, forretningsudvikler, data scientist, softwareudvikler'),
        help='Appen søger på op til fem udtryk og henter op til 25 opslag pr. udtryk. Et tomt felt giver en bred søgning.',
    )
    c1,c2 = st.columns(2)
    use_arbeit = c1.checkbox('Arbeitnow (international)',False)
    use_remotive = c2.checkbox('Remotive (international)',False)
    rss = st.text_area('RSS-feed-adresser (én pr. linje)',value='\n'.join(setting('rss',[])),placeholder='https://eksempel.dk/jobs.rss')
    if st.button('🔎 Find nye job',type='primary'):
        feeds = [x.strip() for x in rss.splitlines() if x.strip()]
        put_setting('rss',feeds)
        put_setting('jobnet_queries', jobnet_queries)
        queries = list(dict.fromkeys(q.strip() for q in jobnet_queries.split(',') if q.strip()))[:5]
        sources = [(f'Jobnet ({q})' if q else 'Jobnet', lambda q=q: fetch_jobnet(q)) for q in queries or ['']]
        if use_arbeit:
            sources.append(('Arbeitnow', fetch_arbeitnow))
        if use_remotive:
            sources.append(('Remotive', fetch_remotive))
        sources += [(url,lambda u=url:fetch_rss(u)) for url in feeds]
        added=0; seen=0; errors=[]
        with st.spinner('Henter stillinger...'):
            for name,fn in sources:
                try:
                    jobs = [job for job in fn() if job.get('title') and job.get('url')]
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
    only_dk = st.checkbox('Vis kun danske arbejdssteder', True, help='Ukendt arbejdssted skjules også; historikken bevares.')
    from job_engine import geography
    filtered = [j for j in rows if (not only_dk or geography(j['location'])[0] >= 45) and j['match']>=minimum and j['status'] in status_filter and query.lower() in (j['title']+' '+j['company']+' '+j['location']).lower()]
    filtered.sort(key=lambda x:x['match'],reverse=True)
    st.caption(f'{len(filtered)} stillinger matcher dine filtre · {len(rows)} i databasen')
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
            with st.popover('Vis jobtekst'):
                st.write((j['description'] or 'Ingen jobtekst')[:18000])

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
