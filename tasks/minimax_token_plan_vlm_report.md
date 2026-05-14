# MiniMax Token Plan VLM synthetic test report

Generated: 2026-05-14 13:10:31 UTC

## Scope

- Synthetic CV-like pages only; no private CVs or repo CV fixtures were sent.
- Endpoint tested: `POST https://api.minimax.io/v1/coding_plan/vlm`.
- Requests: 3; pay-as-you-go equivalent: $0.18; Token Plan quota equivalent: 9 M2.7 requests.

## Results

| Case | HTTP | Latency | Anchors | Czech | Layout | Verdict |
|---|---:|---:|---:|---|---|---|
| `single_column_en` | PASS | 7.21s | 5/5 | PASS | n/a | PASS |
| `bilingual_czech` | PASS | 6.97s | 5/5 | PASS | n/a | PASS |
| `two_column_sidebar` | PASS | 6.45s | 8/8 | PASS | PASS | PASS |

Anchor survival: 18/18 (100%).

## Raw Response Snippets

### `single_column_en`

```text
GANDER SYNTHETIC CV 001 Summary Data Scientist with 5 years building churn models for retail teams Experience - Led customer churn model for Mall.cz pilot reducing cancellations by 11 percent - Built basket demand forecasting model with Python SQL and LightGBM - Owned weekly model monitoring notes for the synthetic analytics team Education CVUT FIT Prague - MSc Informatics 2021
```

### `bilingual_czech`

```text
Jana Testovací Pracovní zkušenosti - Vedla model odchodu zákazníků pro Praha Retail Lab v října 2024 - Navrhla dashboard pro Česko a Slovensko s přesností 93 procent Vzdělání ČVUT FIT - Datová věda, září 2019 - června 2021 Jazyky čeština, angličtina
```

### `two_column_sidebar`

```text
Kontakt Praha, Česko Nejčastější dovednosti Python SQL Certifikace Mini Badge 2026 Alex Synthetic Pracovní zkušenosti Senior Analytics Lead - Founded data quality program for synthetic finance team - Improved forecast review cycle from 9 days to 3 days Vzdělání Test University - Applied Statistics 2018
```

## Recommendation

**usable**

Real CV/Profile.pdf testing remains a separate approval because it sends document content to MiniMax.
