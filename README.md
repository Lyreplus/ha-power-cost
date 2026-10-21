# Power Cost

Integrazione per Home Assistant che calcola il costo dei consumi di un sensore di **potenza** (W), per esempio una presa smart Matter che non riporta i kWh.

Il costo viene calcolato anche sullo **storico già registrato** da Home Assistant, non solo da quando installi l'integrazione.

## Sensori creati

| Sensore | Contenuto |
|---|---|
| Costo oggi / settimana / mese / trimestre / anno | Costo del periodo in corso |
| Costo totale | Costo da quando esistono dati |
| Energia totale | kWh consumati, utilizzabile nella dashboard Energia |

Ogni sensore di costo ha questi attributi: energia (kWh), costo dell'energia, quota fissa, data di inizio dei dati, tariffa attuale e **stima a fine periodo**.

## Come calcola

- **Energia**: Home Assistant conserva per sempre la potenza media di ogni ora (statistiche a lungo termine). Potenza media in kW × 1 ora = kWh di quell'ora. L'ora in corso, non ancora compilata, viene integrata dagli stati registrati.
- **Costo energia**: kWh di ogni giorno × prezzo al kWh in vigore quel giorno.
- **Quota fissa**: ogni giorno matura quota mensile ÷ giorni del mese. Un mese intero costa esattamente la quota mensile, un anno 12 quote. La quota parte dal primo giorno con dati.
- **Stima a fine periodo**: consumo medio finora esteso a tutto il periodo, più la quota fissa dell'intero periodo.

## Requisiti

Il sensore di potenza deve avere `state_class: measurement` (le prese Matter ce l'hanno). Senza, Home Assistant non ne salva le statistiche e la configurazione lo segnala.

## Installazione con HACS

1. HACS → menu ⋮ → **Repository personalizzati** → incolla l'URL di questo repository, tipo **Integrazione**.
2. Cerca **Power Cost**, scaricala e riavvia Home Assistant.
3. Impostazioni → Dispositivi e servizi → **Aggiungi integrazione** → Power Cost.
4. Scegli il sensore di potenza e inserisci il prezzo al kWh e la quota fissa mensile.

Installazione manuale: copia `custom_components/power_cost` in `/config/custom_components/` e riavvia.

## Cambiare tariffa

Impostazioni → Dispositivi e servizi → Power Cost → **Configura**. La nuova tariffa vale dalla data scelta in poi e i costi precedenti restano calcolati con la tariffa di allora. Per correggere un errore, attiva **Applica a tutto lo storico**.

## Sviluppo

```bash
uv venv && uv pip install pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```
