# Domain Hunter

Finds quality expiring/dropping domains on [expireddomains.net](https://www.expireddomains.net),
scores them for **content-site rebuilds**, runs a Wayback-Machine spam-history check, and emails
you a ranked **snipe list** with backorder links and drop dates.

Built for the `pending-delete` list (domains about to drop, still showing live traffic data),
so each pick comes with an **End Date** and a one-click **backorder** link to a drop-catcher.

## How it works

```
login → apply filter (POST) → scrape result pages → parse rows → composite score & rank
      → dedupe vs prior runs → Wayback spam-check top-N → render HTML → email (or preview)
```

- **Filtering** happens on ED.net (the gates: age, Trust Flow, referring domains, etc.).
- **Ranking** happens here — ED.net can only sort one column, so the script computes a
  balanced **0–100 composite score** across four buckets:

  | Bucket | Weight | Signals |
  |---|---|---|
  | Authority | 35 | Trust Flow, referring domains, Wikipedia/.edu/.gov links |
  | Cleanliness | 25 | Trust Ratio (CF/TF, lower=better) + topic coherence; spam-topic penalty |
  | History | 20 | archive age + archive crawl-result depth |
  | Latent traffic | 20 | SEMrush organic keywords + traffic + search volume |

All weights, filter thresholds, and spam markers live in [`config.yaml`](config.yaml) — no code edits needed.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill in credentials
```

`.env` needs:
- **ED.net** login (`EDN_USERNAME` / `EDN_PASSWORD`) — a free account is enough.
- **Gmail SMTP** (`SMTP_*`, `EMAIL_*`) — use a [Gmail App Password](https://myaccount.google.com/apppasswords),
  not your normal password (requires 2FA on the account).

## Usage

```bash
# Dry run: scrape + score + write an HTML preview to output/, send nothing
.venv/bin/python -m domainhunter.main --dry-run

# Full run: send the email and record domains in the dedupe store
.venv/bin/python -m domainhunter.main

# Parse a saved HTML fixture instead of going live (no creds/network needed)
.venv/bin/python -m domainhunter.main --from-fixture tests/fixtures/pendingdelete_sample.html --dry-run

# Other flags
--limit 10      # cap the email to the top 10
--no-wayback    # skip archive.org checks (faster)
--verbose       # debug logging
```

## Scheduling (run it often)

Add a cron entry (e.g. daily at 08:00). Use absolute paths:

```cron
0 8 * * *  cd /Users/james/Coding/Projects/seo-domain-purchaser && .venv/bin/python -m domainhunter.main >> output/cron.log 2>&1
```

The dedupe store (`state/seen_domains.sqlite3`) ensures a domain isn't re-emailed within
`state.suppress_days` (default 30), so frequent runs only surface *new* candidates.

## Layout

```
config.yaml              all tunable settings (filter, weights, spam markers, email)
domainhunter/
  main.py                pipeline entry point + CLI
  config.py              loads config.yaml + .env
  ednet_client.py        login, POST filter, paginate (the ED.net mechanics)
  parser.py              HTML → Candidate (keys off stable field_* CSS classes)
  models.py              Candidate dataclass + number/date parsing
  scorer.py              the composite 0–100 ranking
  wayback.py             archive.org CDX spam-history check
  state.py               SQLite dedupe store
  emailer.py             Jinja2 render + SMTP send
templates/email.html.j2  the email layout
tests/fixtures/          real captured HTML for offline parser tests
```

## Notes & caveats

- **Free data only.** Metrics are Majestic/SEMrush figures as surfaced by ED.net, plus Wayback
  history. There's no paid API. Treat scores as a strong heuristic, not gospel — always eyeball
  the Wayback history (the email links it) before buying.
- **The organic-keywords gate** (`filter.organic_keywords_min`) is meaningful on `pendingdelete`
  (live data) but near-useless on the already-dropped lists (data decays to 0). Set it to `0` to
  widen the net.
- **Sniping** is via whatever backorder provider ED.net links per row (Dynadot/Gname/Catched/etc.).
  You need an account with that provider to actually place the order.
- ED.net's Archive-Birth-Year filter field is confusingly named — the script handles the
  min/max reversal internally (see `ednet_client._build_filter_payload`).
```
