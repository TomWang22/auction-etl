# Phase-D Account-Scope Runtime Triage

> Generated from the conservative whole-repository audit.
> This narrows raw findings to runtime conversion work.

## Summary

- runtime findings: **72**
- non-runtime findings retained in raw audit: **148**
- P0 blockers: **14**
- P1 blockers: **21**
- P2 blockers: **37**
- P3/manual: **0**
- Authlib present in `uv.lock`: **false**

## Runtime findings

| Priority | File | Audit | Writes | Reads | Signals |
| --- | --- | --- | --- | --- | --- |
| **P0** | `app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | `INSERT INTO warehouse.auction_collector`<br>`UPDATE warehouse.auction_collector` | `warehouse.auction_collector` | Streamlit, DATABASE_URL |
| **P0** | `app/pages/10_Listing_Completeness_Review.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | Streamlit, DATABASE_URL |
| **P0** | `app/pages/13_New_Auction_Intake.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | Streamlit |
| **P0** | `app/pages/15_Ingest_New_Auctions.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | Streamlit |
| **P0** | `app/pages/16_Artists_to_Track.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | Streamlit |
| **P0** | `app/pages/2_Completeness_Reference.py` | `MANUAL_REVIEW` | — | — | Streamlit, DATABASE_URL |
| **P0** | `app/pages/2_Pressing_Analytics.py` | `MANUAL_REVIEW` | — | `warehouse.auction_collector_effective` | Streamlit |
| **P0** | `app/pages/3_Latest_Auction_Refresh.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | Streamlit, DATABASE_URL |
| **P0** | `app/pages/4_Reference_Record_Admin.py` | `MANUAL_REVIEW` | — | — | Streamlit, DATABASE_URL |
| **P0** | `auction_etl/services/artist_tracking.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | Streamlit, artist runtime state |
| **P0** | `auction_etl/services/auction_intake.py` | `ACCOUNT_SCOPE_REQUIRED` | `INSERT INTO warehouse.auction_pressing_assignment` | `system.auction_pressing_assignment_audit_event`<br>`system.completeness_cohort_summary`<br>`system.current_listing_completeness_alert`<br>`system.listing_completeness_alert`<br>`system.listing_completeness_snapshot`<br>`system.new_auction_assignment_queue`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_component_expectation`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | Streamlit, DATABASE_URL |
| **P0** | `auction_etl/services/collector_curation.py` | `ACCOUNT_SCOPE_REQUIRED` | `INSERT INTO warehouse.auction_pressing_assignment`<br>`INSERT INTO warehouse.pressing_identity`<br>`INSERT INTO warehouse.release_family` | `system.component_type`<br>`system.condition_grade`<br>`warehouse.auction_analysis_input`<br>`warehouse.auction_completeness`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | — |
| **P0** | `auction_etl/services/refresh_jobs.py` | `ACCOUNT_SCOPE_REQUIRED` | `INSERT INTO ops.refresh_event`<br>`INSERT INTO ops.refresh_job`<br>`INSERT INTO ops.refresh_marketplace`<br>`UPDATE ops.refresh_job`<br>`UPDATE ops.refresh_marketplace` | `ops.refresh_event`<br>`ops.refresh_job`<br>`ops.refresh_marketplace` | Streamlit |
| **P0** | `scripts/run_cloud_refresh_worker.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | Streamlit, DATABASE_URL |
| **P1** | `auction_etl/reporting/main_review_integration.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.auction_ingestion_identity`<br>`warehouse.auction`<br>`warehouse.auction_collector`<br>`warehouse.gripsweat_sale` | DATABASE_URL |
| **P1** | `auction_etl/reporting/recent_ingestion.py` | `MANUAL_REVIEW` | `INSERT INTO system.auction_ingestion_identity`<br>`UPDATE system.auction_ingestion_identity` | `system.auction_ingestion_identity`<br>`warehouse.auction`<br>`warehouse.auction_collector_review` | — |
| **P1** | `auction_etl/services/cohort_curation_wizard.py` | `ACCOUNT_SCOPE_REQUIRED` | `DELETE FROM warehouse.auction_component_observation`<br>`DELETE FROM warehouse.pressing_component_expectation`<br>`INSERT INTO system.evidence_attachment`<br>`INSERT INTO warehouse.auction_component_observation`<br>`INSERT INTO warehouse.pressing_component_expectation` | `system.component_type`<br>`system.evidence_attachment`<br>`system.evidence_source_registry`<br>`system.normalization_work_audit_event`<br>`system.reference_audit_event`<br>`warehouse.auction`<br>`warehouse.auction_analysis_input`<br>`warehouse.auction_comparable_review`<br>`warehouse.auction_completeness`<br>`warehouse.auction_component_observation`<br>`warehouse.auction_condition_normalization`<br>`warehouse.auction_pressing_assignment` | Streamlit |
| **P1** | `auction_etl/services/collector_evidence.py` | `MANUAL_REVIEW` | — | `system.condition_grade`<br>`warehouse.auction`<br>`warehouse.auction_analysis_input`<br>`warehouse.auction_price_snapshot` | Streamlit |
| **P1** | `auction_etl/services/collector_observation_bulk.py` | `ACCOUNT_SCOPE_REQUIRED` | `DELETE FROM warehouse.auction_component_observation`<br>`INSERT INTO system.evidence_source_registry`<br>`INSERT INTO warehouse.auction_component_observation`<br>`UPDATE system.evidence_source_registry` | `system.component_type`<br>`system.evidence_source_registry`<br>`warehouse.auction`<br>`warehouse.auction_component_observation`<br>`warehouse.auction_pressing_assignment` | Streamlit |
| **P1** | `auction_etl/services/completeness_history.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.listing_completeness_snapshot`<br>`system.listing_completeness_timeline`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | Streamlit, DATABASE_URL |
| **P1** | `auction_etl/services/completeness_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | `DELETE FROM warehouse.auction_component_observation`<br>`INSERT INTO warehouse.auction_component_observation` | `system.component_type`<br>`warehouse.auction`<br>`warehouse.auction_component_observation`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_identity` | Streamlit |
| **P1** | `auction_etl/services/crawl.py` | `MANUAL_REVIEW` | — | — | — |
| **P1** | `auction_etl/services/deterministic_verdicts.py` | `MANUAL_REVIEW` | `INSERT INTO system.deterministic_verdict_rule`<br>`UPDATE system.deterministic_verdict_rule` | `system.deterministic_verdict_rule`<br>`system.deterministic_verdict_rule_audit` | Streamlit |
| **P1** | `auction_etl/services/evidence_intake.py` | `MANUAL_REVIEW` | — | `system.component_type`<br>`system.evidence_source_registry` | Streamlit |
| **P1** | `auction_etl/services/ingest.py` | `MANUAL_REVIEW` | — | — | — |
| **P1** | `auction_etl/services/media_aware_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.component_type`<br>`system.evidence_source_registry`<br>`system.media_profile_component`<br>`system.reference_audit_event`<br>`warehouse.auction`<br>`warehouse.auction_component_observation`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_component_expectation`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | Streamlit |
| **P1** | `auction_etl/services/media_profile_admin.py` | `MANUAL_REVIEW` | `DELETE FROM system.media_profile_component`<br>`INSERT INTO system.media_profile_component`<br>`UPDATE system.media_profile_component` | `system.component_type`<br>`system.media_profile_audit_event`<br>`system.media_profile_component`<br>`warehouse.pressing_identity` | — |
| **P1** | `auction_etl/services/normalization_readiness.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `warehouse.auction`<br>`warehouse.auction_completeness`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_component_expectation` | — |
| **P1** | `auction_etl/services/normalization_workbench.py` | `ACCOUNT_SCOPE_REQUIRED` | `INSERT INTO system.normalization_work_batch`<br>`INSERT INTO system.normalization_work_batch_row`<br>`INSERT INTO warehouse.auction_comparable_review`<br>`UPDATE system.normalization_work_batch` | `system.normalization_work_audit_event`<br>`system.normalization_work_batch`<br>`warehouse.auction`<br>`warehouse.auction_comparable_review`<br>`warehouse.auction_component_observation`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_component_expectation`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | Streamlit |
| **P1** | `auction_etl/services/parse.py` | `MANUAL_REVIEW` | — | — | — |
| **P1** | `auction_etl/services/pressing_reference_admin.py` | `ACCOUNT_SCOPE_REQUIRED` | `DELETE FROM warehouse.pressing_component_expectation`<br>`INSERT INTO warehouse.pressing_component_expectation`<br>`INSERT INTO warehouse.pressing_identity`<br>`INSERT INTO warehouse.release_family` | `system.component_type`<br>`warehouse.auction`<br>`warehouse.auction_completeness`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_component_expectation`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | Streamlit |
| **P1** | `auction_etl/services/pressing_reference_catalog.py` | `MANUAL_REVIEW` | `DELETE FROM warehouse.pressing_matrix_runout`<br>`INSERT INTO system.reference_audit_event`<br>`INSERT INTO warehouse.pressing_identity`<br>`INSERT INTO warehouse.pressing_matrix_runout`<br>`INSERT INTO warehouse.release_family`<br>`UPDATE warehouse.pressing_identity` | `warehouse.pressing_identity`<br>`warehouse.pressing_matrix_runout`<br>`warehouse.pressing_reference_catalog` | — |
| **P1** | `auction_etl/services/pressing_reference_workbench.py` | `ACCOUNT_SCOPE_REQUIRED` | `DELETE FROM warehouse.pressing_component_expectation`<br>`INSERT INTO warehouse.pressing_component_expectation` | `system.component_type`<br>`warehouse.auction`<br>`warehouse.auction_completeness`<br>`warehouse.auction_component_observation`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_component_expectation`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | Streamlit |
| **P1** | `auction_etl/services/reference_record_admin.py` | `MANUAL_REVIEW` | `DELETE FROM warehouse.auction_component_observation`<br>`DELETE FROM warehouse.pressing_component_expectation`<br>`INSERT INTO system.bulk_observation_batch`<br>`INSERT INTO system.bulk_observation_batch_row`<br>`INSERT INTO system.evidence_attachment`<br>`INSERT INTO warehouse.auction_component_observation`<br>`INSERT INTO warehouse.pressing_component_expectation`<br>`UPDATE system.bulk_observation_batch`<br>`UPDATE system.evidence_attachment`<br>`UPDATE warehouse.pressing_component_expectation` | `system.bulk_observation_batch`<br>`system.bulk_observation_batch_row`<br>`system.component_type`<br>`system.evidence_attachment`<br>`system.evidence_source_registry`<br>`system.reference_audit_event`<br>`warehouse.auction_component_observation`<br>`warehouse.pressing_component_expectation`<br>`warehouse.pressing_identity` | Streamlit |
| **P1** | `auction_etl/services/state_safe_completeness.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.component_type`<br>`system.media_profile_component`<br>`warehouse.auction`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | — |
| **P2** | `auction_etl/cli/stats.py` | `MANUAL_REVIEW` | — | `warehouse.auction` | — |
| **P2** | `auction_etl/database/collector_views.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `warehouse.auction`<br>`warehouse.auction_collector`<br>`warehouse.auction_collector_effective`<br>`warehouse.auction_collector_review`<br>`warehouse.auction_detail` | Streamlit |
| **P2** | `auction_etl/models/raw.py` | `MANUAL_REVIEW` | — | — | — |
| **P2** | `auction_etl/models/staging.py` | `MANUAL_REVIEW` | — | — | — |
| **P2** | `scripts/audit_auction_docker_contexts.py` | `MANUAL_REVIEW` | — | `warehouse.auction` | Streamlit |
| **P2** | `scripts/audit_collector_db.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `warehouse.auction`<br>`warehouse.auction_collector`<br>`warehouse.auction_collector_effective`<br>`warehouse.auction_detail` | Streamlit |
| **P2** | `scripts/backfill_buyee_displayed_usd.py` | `MANUAL_REVIEW` | `UPDATE warehouse.auction` | `system.auction_ingestion_identity`<br>`warehouse.auction` | DATABASE_URL |
| **P2** | `scripts/collector_features.py` | `ACCOUNT_SCOPE_REQUIRED` | `INSERT INTO warehouse.auction_collector`<br>`UPDATE warehouse.auction_collector` | `warehouse.auction`<br>`warehouse.auction_collector`<br>`warehouse.auction_collector_effective`<br>`warehouse.auction_detail` | — |
| **P2** | `scripts/crawl_buyee_live_details.py` | `MANUAL_REVIEW` | `INSERT INTO warehouse.auction_detail`<br>`UPDATE warehouse.auction` | `system.auction_ingestion_identity`<br>`warehouse.auction`<br>`warehouse.auction_detail` | Streamlit |
| **P2** | `scripts/crawl_ebay_chrome_cdp.py` | `MANUAL_REVIEW` | — | — | Streamlit |
| **P2** | `scripts/crawl_ebay_sources.py` | `MANUAL_REVIEW` | — | `warehouse.auction` | Streamlit |
| **P2** | `scripts/enrich_buyee_details.py` | `MANUAL_REVIEW` | `INSERT INTO warehouse.auction_detail`<br>`UPDATE warehouse.auction` | `warehouse.auction`<br>`warehouse.auction_detail` | — |
| **P2** | `scripts/enrich_gripsweat_details.py` | `MANUAL_REVIEW` | `UPDATE warehouse.gripsweat_sale` | `warehouse.gripsweat_sale` | Streamlit |
| **P2** | `scripts/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | — | `warehouse.pressing_identity`<br>`warehouse.release_family` | Streamlit, DATABASE_URL |
| **P2** | `scripts/hard_test_ingestion_round_ui.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.crawl_job`<br>`system.listing_completeness_snapshot`<br>`system.listing_completeness_timeline`<br>`system.new_auction_assignment_queue`<br>`warehouse.auction`<br>`warehouse.auction_pressing_assignment` | Streamlit, DATABASE_URL |
| **P2** | `scripts/hard_test_latest_refresh_ui.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `warehouse.auction`<br>`warehouse.auction_collector`<br>`warehouse.auction_collector_effective`<br>`warehouse.auction_collector_review` | Streamlit, DATABASE_URL |
| **P2** | `scripts/import_gripsweat_pagination_audit.py` | `MANUAL_REVIEW` | `INSERT INTO warehouse.gripsweat_sale`<br>`UPDATE warehouse.gripsweat_sale` | `warehouse.gripsweat_sale`<br>`warehouse.gripsweat_source` | Streamlit |
| **P2** | `scripts/import_gripsweat_probe.py` | `MANUAL_REVIEW` | `INSERT INTO warehouse.gripsweat_sale`<br>`INSERT INTO warehouse.gripsweat_source`<br>`UPDATE warehouse.gripsweat_sale` | `warehouse.gripsweat_sale` | Streamlit |
| **P2** | `scripts/normalize_gripsweat_sales.py` | `MANUAL_REVIEW` | `UPDATE warehouse.gripsweat_sale` | `warehouse.auction`<br>`warehouse.gripsweat_sale` | DATABASE_URL |
| **P2** | `scripts/normalize_gripsweat_source_schema.py` | `MANUAL_REVIEW` | `INSERT INTO warehouse.gripsweat_source`<br>`UPDATE warehouse.gripsweat_source` | — | DATABASE_URL |
| **P2** | `scripts/probe_buyee_details.py` | `MANUAL_REVIEW` | — | `warehouse.auction` | — |
| **P2** | `scripts/reclassify_collector.py` | `ACCOUNT_SCOPE_REQUIRED` | `UPDATE warehouse.auction_collector` | `warehouse.auction` | — |
| **P2** | `scripts/recover_auction_warehouse.py` | `MANUAL_REVIEW` | `INSERT INTO warehouse.auction` | `warehouse.auction` | DATABASE_URL |
| **P2** | `scripts/repair_recovered_auction_fields.py` | `ACCOUNT_SCOPE_REQUIRED` | `UPDATE warehouse.auction`<br>`UPDATE warehouse.auction_collector` | — | DATABASE_URL |
| **P2** | `scripts/review_and_apply_pressing_packet.py` | `ACCOUNT_SCOPE_REQUIRED` | `DELETE
            FROM warehouse.pressing_component_expectation`<br>`INSERT INTO system.evidence_attachment`<br>`INSERT INTO warehouse.pressing_component_expectation` | `system.evidence_attachment`<br>`system.evidence_source_registry`<br>`system.normalization_work_audit_event`<br>`system.normalization_work_batch`<br>`system.reference_audit_event`<br>`warehouse.auction`<br>`warehouse.auction_analysis_input`<br>`warehouse.auction_behavior_observation`<br>`warehouse.auction_component_observation`<br>`warehouse.auction_condition_normalization`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_component_expectation` | Streamlit |
| **P2** | `scripts/run_buyee_owner.py` | `MANUAL_REVIEW` | — | — | Streamlit, DATABASE_URL |
| **P2** | `scripts/run_fresh_ebay_ingestion_round.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.crawl_job`<br>`system.listing_completeness_snapshot`<br>`system.listing_completeness_timeline`<br>`system.new_auction_assignment_queue`<br>`warehouse.auction`<br>`warehouse.auction_pressing_assignment` | Streamlit, DATABASE_URL |
| **P2** | `scripts/run_ingest_with_assignment_queue.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.listing_completeness_snapshot`<br>`system.listing_completeness_timeline`<br>`system.new_auction_assignment_queue`<br>`warehouse.auction`<br>`warehouse.auction_pressing_assignment` | — |
| **P2** | `scripts/run_latest_auction_refresh.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `warehouse.auction`<br>`warehouse.auction_collector`<br>`warehouse.auction_collector_effective`<br>`warehouse.auction_collector_review`<br>`warehouse.gripsweat_sale` | Streamlit, DATABASE_URL |
| **P2** | `scripts/run_multisource_ingestion_round.py` | `ACCOUNT_SCOPE_REQUIRED` | — | `system.crawl_job`<br>`system.listing_completeness_snapshot`<br>`system.listing_completeness_timeline`<br>`system.new_auction_assignment_queue`<br>`warehouse.auction`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.gripsweat_sale`<br>`warehouse.pressing_identity`<br>`warehouse.release_family` | DATABASE_URL |
| **P2** | `scripts/setup_collector_review_v2.py` | `ACCOUNT_SCOPE_REQUIRED` | — | — | DATABASE_URL |
| **P2** | `scripts/setup_gripsweat_schema.py` | `MANUAL_REVIEW` | — | — | — |
| **P2** | `scripts/setup_pressing_reference_catalog.py` | `ACCOUNT_SCOPE_REQUIRED` | `INSERT INTO warehouse.pressing_matrix_runout`<br>`UPDATE warehouse.pressing_identity` | `warehouse.auction`<br>`warehouse.auction_pressing_assignment`<br>`warehouse.pressing_identity`<br>`warehouse.pressing_matrix_runout`<br>`warehouse.pressing_reference_catalog`<br>`warehouse.release_family` | DATABASE_URL |
| **P2** | `scripts/sync_warehouse_incremental.py` | `MANUAL_REVIEW` | — | `warehouse.auction` | Streamlit, DATABASE_URL |
| **P2** | `scripts/update_auction_fx.py` | `MANUAL_REVIEW` | `UPDATE warehouse.auction` | `warehouse.auction` | DATABASE_URL |
| **P2** | `scripts/update_ingestion_audit.py` | `MANUAL_REVIEW` | — | `system.auction_ingestion_identity` | DATABASE_URL |
| **P2** | `scripts/upgrade_collector_review_schema.py` | `ACCOUNT_SCOPE_REQUIRED` | `UPDATE warehouse.auction`<br>`UPDATE warehouse.auction_collector` | `warehouse.auction` | DATABASE_URL |

## Dependency-lock gate

`pyproject.toml` declares Authlib but `uv.lock` does not yet contain it.

Before committing the dependency change:

```bash
uv lock
```

## Next enforcement gate

Do not apply D1 or the owner backfill yet. Convert P0/P1,
regenerate the audit, then run `scripts/phase_d_scope_gate.py`.
