# Min jobsøgemaskine (Mac)

## Kom i gang

1. Pak ZIP-filen ud.
2. Sørg for at Python 3.10+ er installeret (python.org).
3. Åbn Terminal, skriv `cd ` (med mellemrum), træk den udpakkede `jobfinder`-mappe ind i Terminal og tryk Enter.
4. Kør `bash start_mac.command`.
5. Browseren åbner normalt på http://localhost:8501. Ellers åbn adressen manuelt.
6. Stop programmet med Ctrl+C i Terminal.

Du kan senere starte det med `bash start_mac.command` fra samme mappe. Første opstart kræver internet til installation af Python-pakker.

## Hvad appen kan

- Hente jobopslag fra Jobindex' publicerede RSS-søgeresultater. Angiv fælles søgeord under **Din søgeprofil**, og klik **Find nye job**. Hvert søgeudtryk bruges, og dækningen følger resultaterne i det enkelte feed.
- Hente internationale job fra Arbeitnow og Remotive, hvis du vælger dem.
- Læse RSS-feeds, som du selv tilføjer.
- Gemme jobopslag via URL eller ved at indsætte jobtekst.
- Beregne en vejledende score ud fra fire karrierespor.
- Sammenligne hele den tilgængelige jobtekst med dine erfaringer og karriereønsker. Gem én kompetence eller ét ønske pr. linje under **Din søgeprofil**, og vælg **Analysér opslag** i Joboversigt. Du kan hente eller indsætte den fulde tekst, hvis kilden kun leverer et uddrag.
- Knytte et ChatGPT-samtalelink og uddrag til et job under **Ansøgningssamtale**. Uddrag, du indsætter, sammenlignes med jobteksten under **Analysér opslag**. Link og uddrag gemmes lokalt.
- Eksportere job med status **Ny**, som endnu ikke har en ChatGPT-vurdering. Gå til **Joboversigt → ChatGPT-vurdering af nye job**, download JSON-filen, og upload den i din ChatGPT-samtale sammen med teksten, appen viser. Importér svarfilen samme sted. Vurderinger gemmes efter job-id og vises under **ChatGPT-vurdering** på hvert job.
- Markere job som interessante, ansøgte eller afviste og gemme noter.
- Undgå dubletter på basis af URL; eksportere historik til CSV.

## Begrænsninger

- Jobnet har ingen aktiv søgning. Den [officielle Jobnet-webservice](https://star.dk/digital-service/saadan-arbejder-vi-med-it-i-styrelsen/oversigt-over-digitale-platforme-for-eksterne-brugere/styrelsen-for-arbejdsmarked-og-rekrutterings-webservices-og-wiki/webservice-til-import-og-eksport-af-jobannoncer) kræver en tilslutningsaftale. HR Manager / Talentechs [jobportal-API](https://customerportal.talentech.com/knowledge/talent-recruiter-tr-restful-api-5-1740732494751) er ikke konfigureret. Opslag fra arbejdsgivere på HR Manager kan findes via Jobindex, når arbejdsgiveren har publiceret dem dér.
- **Joboversigt** viser de opslag, der matcher dine filtre. **Historik og eksport** viser alle gemte opslag.
- Matchscoren bruger nøgleord og simple vægte, ikke en sprogmodel. Den kan fejlfortolke job og geografi.
- Nogle karrieresider forhindrer automatisk udtræk; indsæt da jobteksten manuelt.
- Ingen automatisk planlagt søgning eller e-mailnotifikationer endnu.
- Tidligere ansøgninger er ikke automatisk importeret. Registrér dem under 'Historik og eksport'.
- Alle data ligger lokalt i `jobs.sqlite3` i programmappen. Tag backup af den fil.

## Fejlfinding

Hvis macOS blokerer dobbeltklik på .command, brug Terminal-metoden ovenfor. Hvis port 8501 er optaget, viser Streamlit en anden adresse i Terminal.

**Seneste søgning pr. kilde** viser antal hentede, gemte og frasorterede opslag. Under **Joboversigt → Fejlsøg et bestemt opslag** kan du slå titel eller URL op og se importstatus, søgeudtryk og eventuelle visningsfiltre. Søg på titlen, hvis du vil finde en kopi på en anden portal. Importsporet gælder den seneste søgning i den åbne session. Kør regressionstestene for Skattestyrelsens og Jyske Banks opslag med `python -m unittest -v test_job_search`.

### Geografiske præferencer

Første version prioriterer Odense/Fyn og Middelfart-området. Aarhus er også med, men kun stillinger tæt på Aarhus Hovedbanegård er ønskede. Hvis et opslag blot siger Aarhus, markeres afstanden som ukendt og skal kontrolleres manuelt. Der er endnu ingen automatisk adresse- eller gangtidsberegning.
