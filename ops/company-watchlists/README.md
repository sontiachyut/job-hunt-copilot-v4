# Company Watchlists

Generated at: `2026-06-14 19:56:57Z`

`company-watchlist.csv` is the source of truth for the daily job crawler.

Current files:
- `company-watchlist.csv`: 1267 total companies
- `local-watchlist.csv`: 100 derived local-view rows
- `yc-watchlist.csv`: 1168 derived YC-view rows

Recommended workflow:
1. Edit `company-watchlist.csv` directly.
2. Use `segment_tags` to classify companies, for example `local`, `yc`, or `local;yc`.
3. Fill `board_type` and `board_url` as ATS metadata becomes known.
4. Run `python3 scripts/ops/fetch_watchlist_jobs.py` to fetch jobs from supported authoritative API-native listing sources.

Important columns:
- `segment_primary`: the main bucket for sorting and prioritization
- `segment_tags`: semicolon-separated category tags
- `source_lists`: where the company entered the watchlist
- `check_daily`: whether the crawler should include the company every day
- `priority_tier`: your manual ranking layer
- `board_type` / `board_url`: ATS routing metadata for deterministic fetches
- `board_token` / `board_api_url`: resolved ATS identifiers when known
- `board_confirmation_status` / `board_last_verified_at`: latest verification state
- `resolved_from_url`: the page where the board was actually discovered
- `listing_source_type` / `listing_source_url`: the source we trust for live open-role freshness
- `listing_authority`: freshness confidence label such as `api_primary`, `company_primary`, `yc_primary`, or `yc_fallback`
- `fetch_watchlist_jobs.py` currently uses `listing_authority` and `listing_source_type` to fetch only authoritative API-native boards; `yc_primary` and `company_primary` rows stay in the registry but require separate fetchers
- `job_source_type` / `job_source_url`: the deterministic extraction source we should crawl for role data and JD
- `job_source_job_count` / `job_source_last_verified_at`: current observed source state
- `jd_capture_status` / `jd_format`: JD readiness label such as `full_jd_verified`, `full_jd_inferred_api`, or `unconfirmed`
- `jd_extraction_method` / `jd_extraction_locator`: how the deterministic JD fetcher should pull content, for example `same_page_html_sections`, `company_jobs_list_to_detail_pages`, or `yc_jobs_list_to_detail_pages`
- `jd_last_verified_at` / `jd_notes`: latest JD-source validation notes

Seed sources for the current watchlist:
- `ops/local-companies/greater-phoenix-software-100.csv`
- `ops/company-watchlists/yc-api-native-board-confirmation.csv` (`confirmation_status = live_jobs` rows)
- `ops/company-watchlists/yc-us-hiring-recheck-truth.csv` (`live_jobs` and `detected_structured_board` rows)
- `ops/company-watchlists/yc-manual-job-sources.csv` (manual source decisions like `company_careers_page` or `yc_jobs_page`)
