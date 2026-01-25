"""
Spec Kit Feature Standard
=========================

Questo modulo descrive, in forma di *documentazione eseguibile* (docstring),
lo standard di utilizzo di GitHub Spec Kit per questo progetto, con l'obiettivo
di:

1. Avere una struttura **prevedibile** della cartella `specs/`
2. Avere una struttura **prevedibile** per ogni *feature* (sottocartella)
3. Rendere possibile uno script di conversione **Spec Kit → PRD** che potrà
   alimentare un loop autonomo stile Ralph, usando AI Refactor Tool con modelli
   locali (Ollama + Aider).

Questa docstring è pensata per essere letta e seguita da:
- sviluppatori umani
- agenti LLM (es. coding agent in Cursor / AI Refactor Tool)


----------------------------------------------------------------------
1. Inizializzazione del progetto con Spec Kit
----------------------------------------------------------------------

Per inizializzare Spec Kit in un nuovo progetto o in un progetto esistente:

    specify init .

Il comando `specify init .`:

- scarica il template di Spec Kit
- prepara gli script specifici per l'assistente scelto (nel nostro caso
  `cursor-agent` con script type `sh`)
- NON deve cancellare il codice esistente, ma solo aggiungere/configurare
  file nella repo.

Dopo questo comando, la CLI di Spec Kit mostra i *Next Steps* con i comandi
slash disponibili, nella forma:

- /speckit.constitution
- /speckit.specify
- /speckit.plan
- /speckit.tasks
- /speckit.implement
- opzionali:
  - /speckit.clarify
  - /speckit.analyze
  - /speckit.checklist


IMPORTANTE: in questo progetto **NON** useremo `/speckit.implement`,
perché la fase di implementazione è delegata al nostro tool locale (AI Refactor
Tool + Aider + Ollama + loop autonomo stile Ralph).

----------------------------------------------------------------------
2. Struttura standard della cartella specs/
----------------------------------------------------------------------

Obiettivo: avere una struttura di `specs/` che sia:

- coerente tra progetti
- facilmente parseable da uno script Python
- sufficiente a generare un PRD strutturato per ogni feature


2.1. Layout globale

La cartella `specs/` deve seguire questa convenzione:

    specs/
      constitution.md
      system-patterns.md
      tech-context.md
      <feature-id-1>/
        spec.md
        plan.md
        data-model.md
        research.md
        tasks.md
        quickstart.md
        checklists/
          requirements.md
        contracts/
          <service-name>.md
      <feature-id-2>/
        spec.md
        plan.md
        data-model.md
        research.md
        tasks.md
        quickstart.md
        checklists/
          requirements.md
        contracts/
          <service-name>.md
      ...

Dove:

- `constitution.md`:
  - contiene i principi generali del progetto
  - definisce linee guida globali di qualità, testing, UX, ecc.
- `system-patterns.md`:
  - raccoglie pattern architetturali e di implementazione (ad es. “ThemeProvider
    pattern”, “Error handling pattern”, “Data fetching pattern”)
- `tech-context.md`:
  - descrive il contesto tecnico globale: stack, tool, convenzioni di progetto

I file a livello root (`constitution.md`, `system-patterns.md`, `tech-context.md`)
devono essere considerati la **costituzione globale** del progetto, sempre valida
per tutte le feature.

2.2. Naming delle feature (feature-id)

Ogni feature ha una sottocartella con nome:

    <feature-id> = "<numero a 3 cifre>-<slug-kebab-case>"

Esempi:

- `001-ui-theme`
- `002-calendar-appointments`
- `010-ai-refactor-ralph-loop`

La sottocartella si trova direttamente sotto `specs/`:

    specs/001-ui-theme/
    specs/002-calendar-appointments/
    specs/010-ai-refactor-ralph-loop/


----------------------------------------------------------------------
3. Struttura standard per una singola feature
----------------------------------------------------------------------

Ogni feature **deve** essere rappresentata da una sottocartella:

    specs/<feature-id>/

che contiene i seguenti file e cartelle (alcuni opzionali ma raccomandati):

    spec.md                    # obbligatorio
    plan.md                    # obbligatorio
    data-model.md              # opzionale/consigliato
    research.md                # opzionale
    tasks.md                   # obbligatorio
    quickstart.md              # opzionale
    checklists/
      requirements.md          # consigliato (può essere incluso in spec.md se assente)
    contracts/
      <service-name>.md        # opzionale (uno o più file di contratto servizi)

Descrizione dei file:

3.1. spec.md (obbligatorio)
---------------------------

Generato principalmente con:

    /speckit.specify
    (eventualmente seguito da /speckit.clarify)

Contenuti attesi:

- Titolo della feature
- Contesto / motivazione
- User Stories (US1, US2, ...)
- Requisiti funzionali (FR-001, FR-002, ...)
- Criteri di successo / Acceptance Criteria (SC-001, SC-002, ...)
- Assunzioni e vincoli principali

Il file `spec.md` deve essere il documento di riferimento narrativo per
cosa fa la feature e perché.

3.2. plan.md (obbligatorio)
---------------------------

Generato con:

    /speckit.plan

Contenuti attesi:

- Scelta dello stack e delle tecnologie (se rilevante per la feature)
- Architettura tecnica della feature
- Moduli/componenti principali
- Integrazione con il resto del sistema

`plan.md` è la vista “come implementarlo”, ad alto livello tecnico.

3.3. checklists/requirements.md (consigliato)
---------------------------------------------

Può essere generato/arricchito usando:

    /speckit.clarify
    /speckit.checklist (opzionale)

Contenuti attesi:

- Elenco puntuale dei requisiti, con formulazione più rigorosa rispetto
  a `spec.md`
- Può rimappare FR-xxx e SC-xxx in una forma tabellare o bullet list
- Checklist di validazione della specifica (completeness, quality, readiness)

Se `checklists/requirements.md` non esiste, lo script di conversione Spec Kit → PRD
potrà ricavare i requisiti direttamente da `spec.md`, ma la presenza di
`checklists/requirements.md` semplifica parsing e manutenzione.

NOTA: Il file si trova nella sottocartella `checklists/` e non nella root della feature.

3.4. data-model.md (opzionale/consigliato)
------------------------------------------

Modello dati della feature:

- entità
- relazioni
- schemi (anche pseudo-SQL o pseudo-TypeScript)

3.5. research.md (opzionale)
----------------------------

Contiene:

- risultati di `/speckit.analyze`
- analisi cross-artifact
- benchmarking o note di ricerca correlate alla feature

3.6. quickstart.md (opzionale)
-------------------------------

Guida rapida per implementare e testare la feature:

- Prerequisiti e dipendenze
- Setup steps
- Esempi di codice
- Scenari di test manuali
- Checklist di validazione
- Note per il testing

Utile per sviluppatori che devono implementare rapidamente la feature o
validarla manualmente.

3.7. contracts/ (opzionale)
----------------------------

Cartella contenente i contratti dei servizi/moduli della feature.

Ogni file nella cartella `contracts/` descrive il contratto di un servizio
o modulo specifico, tipicamente generato durante la fase di pianificazione.

Formato file: `<service-name>.md`

Contenuti attesi per ogni contratto:

- Nome del servizio/modulo e percorso file
- Scopo del servizio
- Metodi/funzioni esposte con:
  - Descrizione
  - Parametri (tipo e descrizione)
  - Valore di ritorno
  - Gestione errori
  - Comportamenti specifici

Esempio di struttura:

    contracts/
      filter-service.md
      workload-calculator.md
      notification-service.md

3.8. tasks.md (obbligatorio)
----------------------------

Generato con:

    /speckit.tasks

Contenuti attesi:

- Elenco di task granulari, mappati 1:1 a “stories” per il PRD.
- Formato **standardizzato** per facilitare il parsing automatico.

FORMATO TASK STANDARIZZATO:

Si preferisce il formato markdown TODO, ad es.:

    - [ ] T1: Implement ThemeProvider
      - Description: Setup ThemeProvider with light/dark modes and persistence.

    - [ ] T2: Implement ThemeToggle component
      - Description: Add a toggle in the header that switches theme and respects UX specs.

    - [ ] T3: Persist theme in local storage and hydrate on load
      - Description: Ensure theme is restored across page reloads and sessions.

Regole:

- Ogni riga task principale deve iniziare con `- [ ]` (non completato) oppure
  `- [x]` (completato), seguita da un identificatore di task e da un titolo.
- La forma preferita per il titolo è:

      T<n>: <Titolo breve>

  dove:
  - `T<n>` è un ID univoco all’interno della feature (T1, T2, T3, ...)
  - `<Titolo breve>` descrive il task in una frase.

- Le righe successive indentate (con due spazi e `-`) possono descrivere:
  - `Description: ...`
  - dettagli aggiuntivi utili per gli agenti.


----------------------------------------------------------------------
4. Flusso operativo con i comandi Spec Kit
----------------------------------------------------------------------

Questa sezione descrive esattamente la sequenza di comandi `/speckit.*`
da usare con l'agente (es. Cursor) per generare una nuova feature secondo
lo standard.

4.1. Fase foundation globale (una volta per progetto)
-----------------------------------------------------

Nella root del progetto:

1. Inizializzare Spec Kit (se non già fatto):

       specify init .

2. Eseguire:

       /speckit.constitution

   Istruzioni per l’agente (a voce/testo):
   - “Crea/aggiorna i file `specs/constitution.md`, `specs/system-patterns.md`
      e `specs/tech-context.md` con le linee guida globali del progetto.”

4.2. Fase feature-specific (per ogni nuova feature)
---------------------------------------------------

Per ogni nuova feature `<feature-id>`, seguire SEMPRE questo ordine:

1. `/speckit.specify`

   - Chiedere esplicitamente:
     - “Crea `specs/<feature-id>/spec.md` con:
        - user stories (US1, US2, ...)
        - requisiti funzionali (FR-xxx)
        - criteri di successo / acceptance criteria (SC-xxx)
        - assunzioni e vincoli principali.”

2. `/speckit.clarify` (opzionale ma consigliato)

   - Istruzioni:
     - "Usa `/speckit.clarify` per individuare ambiguità nella feature
        `<feature-id>` e aggiorna `specs/<feature-id>/spec.md`.
        Se utile, crea/aggiorna `specs/<feature-id>/checklists/requirements.md` con un
        elenco puntuale dei requisiti."

3. `/speckit.plan`

   - Istruzioni:
     - “Crea il piano tecnico in `specs/<feature-id>/plan.md` specificando:
        - architettura,
        - moduli/componenti,
        - integrazione con il resto del sistema,
        - scelte tecniche rilevanti.”

4. `/speckit.tasks`

   - Istruzioni:
     - “Genera la lista dei task eseguibili per la feature `<feature-id>` in
        `specs/<feature-id>/tasks.md`, usando il formato TODO standard:
        - righe principali `- [ ] T<n>: Titolo...`
        - sotto-bullet `- Description: ...` per i dettagli.”

5. `/speckit.analyze` (opzionale)

   - Se usato:
     - “Esegui `/speckit.analyze` per la feature `<feature-id>` e scrivi i
        risultati in `specs/<feature-id>/research.md` oppure aggiungi una
        sezione dedicata in `plan.md`.”

6. **NON eseguire** `/speckit.implement` per questa feature.

   - L'implementazione automatica sarà eseguita dal nostro **loop autonomo**
     basato su AI Refactor Tool, che:
       - leggerà i file in `specs/<feature-id>/`
       - genererà un PRD (`prd.json`)
       - itererà sui task/stories usando Aider + modelli Ollama.


----------------------------------------------------------------------
5. Requisiti per lo script Spec Kit → PRD
----------------------------------------------------------------------

Lo script di conversione (che verrà implementato in un modulo separato,
ad esempio `prd_generator.py`) può assumere quanto segue:

- La struttura di `specs/` è quella definita sopra.
- Per una feature `<feature-id>` esiste la cartella `specs/<feature-id>/`.
- All'interno della cartella feature esistono **almeno**:
  - `spec.md`
  - `plan.md`
  - `tasks.md`
- Opzionalmente possono esistere:
  - `data-model.md`
  - `research.md`
  - `quickstart.md`
  - `checklists/requirements.md`
  - `contracts/<service-name>.md` (uno o più file)
- Il formato dei task in `tasks.md` segue le regole del paragrafo 3.8:
  - righe `- [ ] T<n>: Titolo`
  - eventuali descrizioni sotto forma di bullet indentati (`- Description: ...`).

A partire da questi file, lo script dovrà:

1. Estrarre:
   - una descrizione generale della feature (da `spec.md` e/o `plan.md`)
   - una lista di **stories** corrispondenti ai task (`T1`, `T2`, ...)

2. Creare un file `specs/<feature-id>/prd.json` con schema simile:

   ```json
   {
     "feature_id": "<feature-id>",
     "title": "<titolo sintetico della feature>",
     "description": "<descrizione high-level>",
     "stories": [
       {
         "id": "T1",
         "title": "Implement ThemeProvider",
         "description": "Setup ThemeProvider with light/dark modes and persistence...",
         "acceptance_criteria": [
           "..."
         ],
         "status": "todo",
         "attempts": 0,
         "last_error": null
       }
     ]
   }
