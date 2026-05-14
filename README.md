# Portfolio Tracker — Backend API

Backend FastAPI stateless pour l'outil de suivi de portefeuille Trade Republic.  
Conçu pour être déployé gratuitement sur [Render](https://render.com) ou [Fly.io](https://fly.io).

**Frontend** → [portfolio-tracker](https://nico20167.github.io/Portfolio-Tracker/)

---

## Principe de fonctionnement

Le backend est **100 % stateless** : il ne stocke aucune donnée utilisateur.  
À chaque requête, le frontend envoie les données dans le body (JSON), le backend calcule et renvoie le résultat. Les données restent dans le `localStorage` du navigateur de l'utilisateur.

```
Navigateur                         API (ce repo)
──────────────                     ─────────────────────────────────
localStorage           ──POST──►   Traitement en mémoire (SQLite :memory:)
{transactions,                     Calcul analytics
 prices,               ◄────────   Résultat JSON
 metadata}
```

---

## Endpoints

| Méthode | Route | Description |
|---|---|---|
| `GET`  | `/api/ping` | Health check (keep-alive Render) |
| `POST` | `/api/parse` | Parse un CSV Trade Republic → retourne les transactions |
| `POST` | `/api/enrich-isin` | Géo/secteurs + historique de prix pour un ISIN via JustETF |
| `POST` | `/api/compute` | Calcule tous les analytics (positions, évolution, répartition…) |
| `POST` | `/api/compute/etf` | Évolution + transactions pour un ETF spécifique |
| `POST` | `/api/compute/price` | Historique de prix d'un ETF sur une période |
| `POST` | `/api/compute/benchmark` | Comparaison portefeuille vs S&P 500 (base 100) |
| `POST` | `/api/compute/performance` | Performance sur une période (1M, MTD, YTD, Max) |
| `POST` | `/api/compute/allocation-detail` | Détail d'une exposition géographique ou sectorielle |

---

## Stack

- **Python 3.11+**
- **FastAPI** — framework web
- **pandas** — parsing CSV
- **justetf-scraping** — cours et données ETF depuis JustETF
- **SQLite `:memory:`** — base temporaire par requête, détruite après

---

## Lancer en local

```bash
# Cloner le repo
git clone https://github.com/Nico20167/portfolio-tracker-api.git
cd portfolio-tracker-api

# Installer les dépendances
pip install -r requirements.txt

# Démarrer le serveur
uvicorn main:app --reload --port 8000
```

L'API est disponible sur `http://localhost:8000`.  
Le frontend doit pointer sur `http://localhost:8000/api` (détecté automatiquement si servi depuis le même hôte).

---

## Déployer sur Render (gratuit)

1. Crée un compte sur [render.com](https://render.com) et connecte ton GitHub
2. **New → Web Service** → sélectionne ce repo
3. Configure :

| Champ | Valeur |
|---|---|
| Environment | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Plan | `Free` |

4. Clique **Deploy** → Render te donne une URL `https://xxx.onrender.com`
5. Mets à jour cette URL dans le `index.html` du frontend :
   ```javascript
   : 'https://xxx.onrender.com/api';
   ```

> **Note** : le free tier Render s'endort après 15 min d'inactivité. Le premier appel après inactivité prend ~30s (cold start). Pour éviter ça, configure un monitor sur [UptimeRobot](https://uptimerobot.com) (gratuit) pointant sur `/api/ping` toutes les 5 minutes.

---

## Fichiers

```
portfolio-api/
├── main.py                   # Endpoints FastAPI, logique stateless
├── analytics.py              # Calculs : positions, TWRR, MWRR, répartition…
├── enricher.py               # Récupération données JustETF + compositions d'indices
├── etf_compositions.json     # Données de composition des indices (geo + secteurs)
├── database.py               # Utilitaire SQLite in-memory + injection de connexion
├── parser.py                 # (inutilisé en prod, conservé pour usage local)
└── requirements.txt
```

---

## ETFs supportés

Les ETF **physiques** (iShares, Vanguard, Xtrackers…) sont enrichis en temps réel via JustETF : composition géographique et sectorielle exacte, cours historiques.

Les ETF **synthétiques PEA** (Amundi, BNP, Lyxor à domiciliation française) ne publient pas de composition sur JustETF. Pour eux, `enricher.py` utilise un fallback sur les compositions d'indices connues, chargées depuis **`etf_compositions.json`**.

### Indices couverts (fallback synthétiques)

`MSCI World` · `MSCI Emerging Markets` · `MSCI India` · `MSCI Japan` · `MSCI Korea` · `MSCI Taiwan` · `MSCI Brazil` · `MSCI China` · `MSCI Vietnam` · `MSCI Indonesia` · `MSCI ACWI` · `MSCI USA` · `MSCI Europe` · `MSCI Europe ex-UK` · `MSCI EMU` · `MSCI Pacific ex-Japan` · `MSCI World Small Cap` · `MSCI World Quality` · `MSCI World Momentum` · `STOXX Europe 600` · `Euro Stoxx 50` · `S&P 500` · `NASDAQ-100` · `Russell 2000` · `CAC 40` · `DAX 40` · `FTSE 100` · `FTSE All-World` · `FTSE Developed World` · `Nikkei 225` · `HSCEI China` · `Bloomberg Europe Defense` · `Global Clean Energy`

L'indice est détecté automatiquement à partir du nom de l'ETF tel qu'il apparaît dans l'export Trade Republic, ou via le mapping ISIN explicite dans le JSON.

### Ajouter un ETF ou mettre à jour une composition

Éditer uniquement **`etf_compositions.json`** — aucun changement Python requis :

```json
{
  "geo":           { "Mon Indice": { "France": 50.0, "Germany": 50.0 } },
  "sectors":       { "Mon Indice": { "Financials": 30.0, "Industrials": 70.0 } },
  "isin_to_index": { "FR0012345678": "Mon Indice" },
  "name_patterns": [ ["mon.indice", "Mon Indice"] ]
}
```

> **Note** : les compositions sont approximatives (sources : factsheets MSCI, STOXX, FTSE, 2024-2025) et évoluent avec les rebalancements trimestriels des indices.
