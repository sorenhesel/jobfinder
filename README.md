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

- Hente job fra de åbne API'er Arbeitnow og Remotive.
- Læse RSS-feeds, som du selv tilføjer.
- Gemme jobopslag via URL eller ved at indsætte jobtekst.
- Beregne en vejledende score ud fra fire karrierespor.
- Markere job som interessante, ansøgte eller afviste og gemme noter.
- Undgå dubletter på basis af URL; eksportere historik til CSV.

## Begrænsninger

- De indbyggede kilder er primært internationale og kan give få danske job. Danske jobportaler er ikke integreret automatisk i denne version.
- Matchscoren bruger nøgleord og simple vægte, ikke en sprogmodel. Den kan fejlfortolke job og geografi.
- Nogle karrieresider forhindrer automatisk udtræk; indsæt da jobteksten manuelt.
- Ingen automatisk planlagt søgning eller e-mailnotifikationer endnu.
- Tidligere ansøgninger er ikke automatisk importeret. Registrér dem under 'Historik og eksport'.
- Alle data ligger lokalt i `jobs.sqlite3` i programmappen. Tag backup af den fil.

## Fejlfinding

Hvis macOS blokerer dobbeltklik på .command, brug Terminal-metoden ovenfor. Hvis port 8501 er optaget, viser Streamlit en anden adresse i Terminal.

### Geografiske præferencer

Første version prioriterer Odense/Fyn og Middelfart-området. Aarhus er også med, men kun stillinger tæt på Aarhus Hovedbanegård er ønskede. Hvis et opslag blot siger Aarhus, markeres afstanden som ukendt og skal kontrolleres manuelt. Der er endnu ingen automatisk adresse- eller gangtidsberegning.

### Dansk søgning (rettelse)
Internationale API-kilder er nu slået fra som standard. Fanen Find nye job har links til danske websøgninger; relevante links kan importeres manuelt. Under Joboversigt er et filter for danske arbejdssteder slået til som standard. Dette er **ikke** automatisk indlæsning fra danske jobportaler. Eksisterende data i jobs.sqlite3 bevares, hvis du kopierer filen fra den gamle mappe til den nye.
