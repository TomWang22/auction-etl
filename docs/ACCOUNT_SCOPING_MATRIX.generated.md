# Generated Account-Scoping Matrix

> Static discovery output. Human review is required before any
> account-enforcement migration is allowed.

## Summary

- files scanned: **1750**
- account scope required: **120**
- manual review: **100**

## Required conversions

| File | Relations | Reason |
| --- | --- | --- |
| `README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `app/pages/10_Listing_Completeness_Review.py` | — | Known user/workflow surface requires account authorization before multi-user enablement. |
| `app/pages/13_New_Auction_Intake.py` | — | Known user/workflow surface requires account authorization before multi-user enablement. |
| `app/pages/15_Ingest_New_Auctions.py` | — | Known user/workflow surface requires account authorization before multi-user enablement. |
| `app/pages/16_Artists_to_Track.py` | — | Known user/workflow surface requires account authorization before multi-user enablement. |
| `app/pages/3_Latest_Auction_Refresh.py` | `ops.refresh_job` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/database/collector_views.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/reporting/main_review_integration.py` | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.gripsweat_sale` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/artist_tracking.py` | — | Known user/workflow surface requires account authorization before multi-user enablement. |
| `auction_etl/services/auction_intake.py` | `system.auction_pressing_assignment_audit_event`, `system.completeness_cohort_summary`, `system.current_listing_completeness_alert`, `system.listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.new_auction_assignment_queue`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/cohort_curation_wizard.py` | `analytics.auction_collector_base`, `system.component_type`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_comparable_review`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/collector_curation.py` | `analytics.auction_scores`, `analytics.emotional_damage`, `system.component_type`, `system.condition_grade`, `warehouse.auction_analysis_input`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/collector_observation_bulk.py` | `system.component_type`, `system.evidence_source_registry`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/completeness_history.py` | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/completeness_reference.py` | `system.component_type`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/media_aware_reference.py` | `system.component_type`, `system.evidence_source_registry`, `system.media_profile_component`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/normalization_readiness.py` | `analytics.auction_collector_base`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/normalization_workbench.py` | `analytics.auction_collector_base`, `analytics.normalization_work_queue`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_comparable_review`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/pressing_reference_admin.py` | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/pressing_reference_workbench.py` | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/refresh_jobs.py` | `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace` | References durable account-sensitive state without an explicit account boundary. |
| `auction_etl/services/state_safe_completeness.py` | `system.component_type`, `system.media_profile_component`, `warehouse.auction`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `backups/collector-analytics-editor-20260802-121838/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/factory-sealed-autofill-resume-20260803-002517/completeness_reference.py` | `system.component_type`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `backups/factory-sealed-autofill-resume-20260803-002717/completeness_reference.py` | `system.component_type`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `backups/factory-sealed-autofill-resume-20260803-101821/completeness_reference.py` | `system.component_type`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `backups/general-reference-workbench-finish-20260803-145638/auction_etl_services_pressing_reference_workbench.py` | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `backups/generated-behavior-fix-20260802-213622/collector_curation.py` | `analytics.auction_scores`, `analytics.emotional_damage`, `system.component_type`, `system.condition_grade`, `warehouse.auction_analysis_input`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `backups/generated-behavior-v2-20260802-214618/collector_curation.py` | `analytics.auction_scores`, `analytics.emotional_damage`, `system.component_type`, `system.condition_grade`, `warehouse.auction_analysis_input`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `backups/pressing-reference-search-fix-20260803-111313/pressing_reference_admin.py` | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-export-ui-20260801-095114/README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-export-ui-20260801-095114/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-hover-click-20260731-215531/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-223948/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-review-recovery-20260727-165333/collector_features.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-view-20260727-155914/collector_features.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-view-final-20260727-161510/collector_features.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/collector-view-owner-20260728-095124/scripts_collector_features.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/dict-row-fix-20260730-144916/run_latest_auction_refresh.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.gripsweat_sale` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/duplicate-columns-20260731-142908/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/duplicate-columns-20260731-142908/auction_etl/reporting/main_review_integration.py` | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.gripsweat_sale` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/export-ui-fix-20260801-095704/README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/export-ui-fix-20260801-095704/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/helper-relocation-20260731-143250/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/helper-relocation-20260731-143250/auction_etl/reporting/main_review_integration.py` | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.gripsweat_sale` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/scripts_hard_test_latest_refresh_ui.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/latest-reporting-finalize-20260730-164007/auction_etl_database_collector_views.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/live-ui-repair-20260730-185406/app_collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/main-integration-20260730-195442/app_collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/pagination-key-20260730-190407/app_collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/recent-export-20260801-155634/README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/recent-export-20260801-155634/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/restore-port-5544-20260801-140934/README.md` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/restore-port-5544-20260801-140934/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/review-toc-20260727-170916/collector_features.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/selection-redesign-20260731-162928/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165210/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165811/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-173808/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/source-aware-20260731-100903/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/streamlit-width-20260731-152713/app/collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/update-status-20260730-191418/app_collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `backups/private/runtime-scripts/update-status-v2-20260730-192538/app_collector_review.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-owner/source-drift-20260728-100946/collector_features.evidence.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-171739/auction_collector_effective.sql` | `warehouse.auction`, `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-171739/auction_collector_review.sql` | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-171739/collector_features.c80774e.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-172854/auction_collector_effective.sql` | `warehouse.auction`, `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-172854/auction_collector_review.sql` | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-172854/collector_features.c80774e.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-173819/auction_collector_effective.sql` | `warehouse.auction`, `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-173819/auction_collector_review.sql` | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-ownership/20260727-173819/collector_features.c80774e.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-recovery/toc-20260727-170916/auction_collector_review.sql` | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/collector-view-repair/final-20260727-161510/managed-views-before.sql` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-history-identity-fix-20260804-214023/before-fix/auction_etl/services/completeness_history.py` | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-history-identity-fix-20260804-214023/before-fix/tests/test_completeness_history.py` | `system.listing_completeness_snapshot` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline_down.sql` | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.completeness_changed_fields`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_component`, `system.reject_completeness_snapshot_mutation`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline_up.sql` | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.completeness_changed_fields`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_component`, `system.reject_completeness_snapshot_mutation`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/auction_etl/services/completeness_history.py` | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/tests/test_completeness_history.py` | `system.listing_completeness_snapshot` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/tests/test_completeness_history_migration.py` | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment` | References durable account-sensitive state without an explicit account boundary. |
| `logs/completeness-snapshot-contract-20260804-182919/contract.json` | `system.capture_media_profile_audit`, `system.capture_reference_audit`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_audit_event`, `system.media_profile_audit_event_id_seq`, `system.media_profile_component`, `system.normalization_work_audit_event`, `system.normalization_work_audit_event_id_seq`, `system.reference_audit_event`, `system.reference_audit_event_id_seq`, `system.reject_media_profile_audit_mutation`, `system.reject_reference_audit_mutation`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_component_observation_id_seq`, `warehouse.auction_id_seq`, `warehouse.auction_pressing_assignment`, `warehouse.auction_pressing_assignment_id_seq`, `warehouse.pressing_component_expectation`, `warehouse.pressing_component_expectation_id_seq`, `warehouse.pressing_identity`, `warehouse.pressing_identity_id_seq` | References durable account-sensitive state without an explicit account boundary. |
| `logs/component-registry-discovery-20260804-130403/pending-before-fix/review_and_apply_pressing_packet.py` | `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.component_type`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/media-aware-reference-contract-20260804-170108/contract.json` | `system.bulk_observation_batch_row`, `system.component_type`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_component_expectation_id_seq`, `warehouse.pressing_identity`, `warehouse.pressing_identity_id_seq`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/media-reference-quantity-fix-20260804-172326/before-fix/media_aware_reference.py` | `system.component_type`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/missing-ebay-source-diagnostic-20260805-214748/relation-inventory.json` | `analytics.auction_alerts`, `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.completeness_premium`, `analytics.emotional_damage`, `analytics.midfication_detection`, `analytics.normalization_work_queue`, `analytics.obi_premium`, `analytics.obi_variant_price_summary`, `analytics.pressing_assignment_queue`, `raw.page`, `system.auction_ingestion_identity`, `system.auction_pressing_assignment_audit_event`, `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.completeness_cohort_summary`, `system.component_type`, `system.condition_grade`, `system.crawl_job`, `system.current_listing_completeness_alert`, `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.new_auction_assignment_queue`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `system.reference_audit_event`, `system.source`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_comparable_review`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_detail`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.auction_price_snapshot`, `warehouse.auction_purchase_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source`, `warehouse.listing_lineage`, `warehouse.listing_lineage_member`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/missing-ebay-source-diagnostic-20260805-225154/relation-inventory.json` | `analytics.auction_alerts`, `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.completeness_premium`, `analytics.emotional_damage`, `analytics.midfication_detection`, `analytics.normalization_work_queue`, `analytics.obi_premium`, `analytics.obi_variant_price_summary`, `analytics.pressing_assignment_queue`, `raw.page`, `system.auction_ingestion_identity`, `system.auction_pressing_assignment_audit_event`, `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.completeness_cohort_summary`, `system.component_type`, `system.condition_grade`, `system.crawl_job`, `system.current_listing_completeness_alert`, `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.new_auction_assignment_queue`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `system.reference_audit_event`, `system.source`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_comparable_review`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_detail`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.auction_price_snapshot`, `warehouse.auction_purchase_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source`, `warehouse.listing_lineage`, `warehouse.listing_lineage_member`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/new-auction-ingest-contract-20260804-234929/contract.json` | `raw.py`, `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.capture_media_profile_audit`, `system.capture_reference_audit`, `system.completeness_changed_fields`, `system.component_type`, `system.condition_grade`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_snapshot_id_seq`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.py`, `system.reject_completeness_snapshot_mutation`, `system.reject_media_profile_audit_mutation`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_component_observation_id_seq`, `warehouse.auction_id_seq`, `warehouse.auction_pressing_assignment`, `warehouse.auction_pressing_assignment_id_seq`, `warehouse.pressing_component_expectation`, `warehouse.pressing_component_expectation_id_seq`, `warehouse.pressing_identity`, `warehouse.pressing_identity_id_seq`, `warehouse.py`, `warehouse.release_family`, `warehouse.release_family_id_seq` | References durable account-sensitive state without an explicit account boundary. |
| `logs/safe-sync-repair/continuation-20260727-144115/backfill.sql` | `warehouse.auction`, `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `logs/schema-audit/20260727-133328/schema-audit.sql` | `raw.page`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source` | References durable account-sensitive state without an explicit account boundary. |
| `logs/schema-audit/continuation-20260727-142310/schema-audit-continuation.sql` | `raw.page`, `system.crawl_job`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail`, `warehouse.auction_purchase_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source` | References durable account-sensitive state without an explicit account boundary. |
| `logs/sealed-completeness-contract-v2-20260803-001355/auction-collector-base-view.sql` | `system.condition_grade`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.listing_lineage_member`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/sealed-completeness-contract-v2-20260803-001355/auction-completeness-view.sql` | `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` | References durable account-sensitive state without an explicit account boundary. |
| `logs/stage3-legacy-schema-fix-20260804-125913/pending-before-fix/review_and_apply_pressing_packet.py` | `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.component_type`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/state-safe-media-profiles-20260804-174018/source-before-install/media_aware_reference.py` | `system.component_type`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/state-safe-media-profiles-20260804-174402/source-before-install/media_aware_reference.py` | `system.component_type`, `system.evidence_source_registry`, `system.media_profile_component`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `logs/state-safe-media-profiles-20260804-180433/source-before-install/media_aware_reference.py` | `system.component_type`, `system.evidence_source_registry`, `system.media_profile_component`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/audit_collector_db.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/collector_features.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/hard_test_ingestion_round_ui.py` | `raw.page`, `system.crawl_job`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/hard_test_latest_refresh_ui.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/reclassify_collector.py` | `warehouse.auction`, `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/repair_recovered_auction_fields.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_detail` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/review_and_apply_pressing_packet.py` | `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/run_cloud_refresh_worker.py` | — | Known user/workflow surface requires account authorization before multi-user enablement. |
| `scripts/run_fresh_ebay_ingestion_round.py` | `identity.listing_id`, `identity.marketplace`, `raw.page`, `system.crawl_job`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/run_ingest_with_assignment_queue.py` | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/run_latest_auction_refresh.py` | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.gripsweat_sale` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/run_multisource_ingestion_round.py` | `identity.listing_id`, `identity.marketplace`, `raw.page`, `system.crawl_job`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment`, `warehouse.gripsweat_sale`, `warehouse.pressing_identity`, `warehouse.pressing_matrix_runout`, `warehouse.pressing_reference_catalog`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/setup_collector_review_v2.py` | `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/setup_pressing_reference_catalog.py` | `warehouse.auction`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.pressing_matrix_runout`, `warehouse.pressing_reference_catalog`, `warehouse.release_family` | References durable account-sensitive state without an explicit account boundary. |
| `scripts/upgrade_collector_review_schema.py` | `warehouse.auction`, `warehouse.auction_collector` | References durable account-sensitive state without an explicit account boundary. |

## Full inventory

| File | Classification | DB URL | Streamlit | Account context | Relations |
| --- | --- | --- | --- | --- | --- |
| `.streamlit/config.toml` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `alembic/env.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `alembic/versions/0428279b6f87_allow_page_history.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/4c4e55331d0d_initial_warehouse_schema.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/7c3e8a1d5f42_evidence_source_registry.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/7c3e8a1d5f42_evidence_source_registry_down.sql` | `MIGRATION` | false | false | false | `system.evidence_source_registry` |
| `alembic/versions/7c3e8a1d5f42_evidence_source_registry_up.sql` | `MIGRATION` | false | false | false | `system.evidence_source_registry`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation` |
| `alembic/versions/9e4b7c2a6d15_reference_audit_and_attachments.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/9e4b7c2a6d15_reference_audit_and_attachments_down.sql` | `MIGRATION` | false | false | false | `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.capture_reference_audit`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.reference_audit_event`, `system.reject_reference_audit_mutation`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation` |
| `alembic/versions/9e4b7c2a6d15_reference_audit_and_attachments_up.sql` | `MIGRATION` | false | false | false | `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.capture_reference_audit`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.reference_audit_event`, `system.reject_reference_audit_mutation`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation` |
| `alembic/versions/a4d9c2e7f105_account_identity_foundation.py` | `MIGRATION` | false | false | true | — |
| `alembic/versions/a4d9c2e7f105_account_identity_foundation_down.sql` | `MIGRATION` | false | false | true | `ops.refresh_job`, `ops.refresh_job_account_created_idx`, `system.auction_pressing_assignment_audit_event`, `system.current_listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction_collector`, `warehouse.auction_pressing_assignment` |
| `alembic/versions/a4d9c2e7f105_account_identity_foundation_up.sql` | `MIGRATION` | false | false | true | `account.artist_marketplace`, `account.auction_listing`, `account.marketplace_connection`, `account.tracked_artist`, `identity.account`, `identity.account_member`, `identity.app_user`, `ops.refresh_job`, `system.auction_pressing_assignment_audit_event`, `system.current_listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction_collector`, `warehouse.auction_pressing_assignment` |
| `alembic/versions/be7b9855a5dc_add_uniqueness_constraints.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/c1f4e8b7a630_normalization_and_verdict_rules.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/c1f4e8b7a630_normalization_and_verdict_rules_down.sql` | `MIGRATION` | false | false | false | `system.capture_verdict_rule_audit`, `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `system.reject_verdict_rule_audit_mutation` |
| `alembic/versions/c1f4e8b7a630_normalization_and_verdict_rules_up.sql` | `MIGRATION` | false | false | false | `system.capture_verdict_rule_audit`, `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `system.reject_verdict_rule_audit_mutation` |
| `alembic/versions/c4aba410158b_add_crawl_job.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/c4f8a2d7e901_collector_analytics_down.sql` | `MIGRATION` | false | false | false | `analytics.auction_alerts`, `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.comparable_confidence`, `analytics.completeness_premium`, `analytics.emotional_damage`, `analytics.midfication_detection`, `analytics.obi_premium`, `analytics.obi_variant_price_summary`, `analytics.pressing_assignment_queue`, `system.component_type`, `system.condition_grade`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.auction_price_snapshot`, `warehouse.listing_lineage`, `warehouse.listing_lineage_member`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `alembic/versions/c4f8a2d7e901_collector_analytics_foundation.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/c4f8a2d7e901_collector_analytics_up.sql` | `MIGRATION` | false | false | false | `analytics.auction_alerts`, `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.comparable_confidence`, `analytics.completeness_premium`, `analytics.emotional_damage`, `analytics.midfication_detection`, `analytics.obi_premium`, `analytics.obi_variant_price_summary`, `analytics.pressing_assignment_queue`, `system.component_type`, `system.condition_grade`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.auction_price_snapshot`, `warehouse.listing_lineage`, `warehouse.listing_lineage_member`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `alembic/versions/c8b4d7e2a619_new_auction_intake_queue_and_alerts.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/c8b4d7e2a619_new_auction_intake_queue_and_alerts_down.sql` | `MIGRATION` | false | false | false | `system.auction_pressing_assignment_audit_event`, `system.capture_auction_pressing_assignment_audit`, `system.completeness_cohort_summary`, `system.current_listing_completeness_alert`, `system.listing_completeness_alert`, `system.new_auction_assignment_queue`, `system.reject_assignment_audit_mutation`, `warehouse.auction_pressing_assignment` |
| `alembic/versions/c8b4d7e2a619_new_auction_intake_queue_and_alerts_up.sql` | `MIGRATION` | false | false | false | `system.auction_pressing_assignment_audit_event`, `system.capture_auction_pressing_assignment_audit`, `system.completeness_cohort_summary`, `system.current_listing_completeness_alert`, `system.listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.new_auction_assignment_queue`, `system.reject_assignment_audit_mutation`, `warehouse.auction`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline_down.sql` | `MIGRATION` | false | false | false | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.completeness_changed_fields`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_component`, `system.reject_completeness_snapshot_mutation`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation` |
| `alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline_up.sql` | `MIGRATION` | false | false | false | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.completeness_changed_fields`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_component`, `system.reject_completeness_snapshot_mutation`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` |
| `alembic/versions/d8a41f6c2b70_emotional_damage_minimum_coverage.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/d8a41f6c2b70_emotional_damage_minimum_coverage_down.sql` | `MIGRATION` | false | false | false | `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.emotional_damage` |
| `alembic/versions/d8a41f6c2b70_emotional_damage_minimum_coverage_up.sql` | `MIGRATION` | false | false | false | `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.emotional_damage` |
| `alembic/versions/e7b3c6d9a214_normalization_workbench.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/e7b3c6d9a214_normalization_workbench_down.sql` | `MIGRATION` | false | false | false | `analytics.normalization_work_queue`, `system.capture_normalization_work_audit`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `system.reject_normalization_audit_mutation`, `warehouse.auction_analysis_input`, `warehouse.auction_comparable_review`, `warehouse.auction_condition_normalization` |
| `alembic/versions/e7b3c6d9a214_normalization_workbench_up.sql` | `MIGRATION` | false | false | false | `analytics.auction_collector_base`, `analytics.normalization_work_queue`, `system.capture_normalization_work_audit`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `system.reject_normalization_audit_mutation`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_comparable_review`, `warehouse.auction_completeness`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `alembic/versions/f2a7c9e4b610_factory_sealed_completeness_exception.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/f2a7c9e4b610_factory_sealed_completeness_exception_down.sql` | `MIGRATION` | false | false | false | `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` |
| `alembic/versions/f2a7c9e4b610_factory_sealed_completeness_exception_up.sql` | `MIGRATION` | false | false | false | `system.component_type`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` |
| `alembic/versions/f31a9c7d2e04_durable_refresh_coordination.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/f31a9c7d2e04_durable_refresh_coordination_down.sql` | `MIGRATION` | false | false | false | `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace` |
| `alembic/versions/f31a9c7d2e04_durable_refresh_coordination_up.sql` | `MIGRATION` | false | false | false | `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace` |
| `alembic/versions/f9d6a2c4e781_media_profiles_and_state_safe_completeness.py` | `MIGRATION` | false | false | false | — |
| `alembic/versions/f9d6a2c4e781_media_profiles_and_state_safe_completeness_down.sql` | `MIGRATION` | false | false | false | `system.capture_media_profile_audit`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.reject_media_profile_audit_mutation` |
| `alembic/versions/f9d6a2c4e781_media_profiles_and_state_safe_completeness_up.sql` | `MIGRATION` | false | false | false | `system.capture_media_profile_audit`, `system.component_type`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.reject_media_profile_audit_mutation` |
| `api/index.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `app/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/collector_export.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `app/navigation.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `app/pages/10_Listing_Completeness_Review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | — |
| `app/pages/11_Media_Profile_Admin.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/pages/12_Completeness_History.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `app/pages/13_New_Auction_Intake.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | — |
| `app/pages/14_Pressing_Reference_Catalog.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/pages/15_Ingest_New_Auctions.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | — |
| `app/pages/16_Artists_to_Track.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | — |
| `app/pages/1_Home.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `app/pages/2_Completeness_Reference.py` | `MANUAL_REVIEW` | true | true | false | `identity.get` |
| `app/pages/2_Pressing_Analytics.py` | `MANUAL_REVIEW` | false | true | false | `warehouse.auction_collector_effective` |
| `app/pages/3_Evidence_and_Bulk_Observations.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/pages/3_Latest_Auction_Refresh.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `ops.refresh_job` |
| `app/pages/4_Reference_Record_Admin.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_component_expectation` |
| `app/pages/5_Normalization_Readiness.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/pages/6_Deterministic_Verdict_Rules.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/pages/7_Normalization_Workbench.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/pages/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `app/pages/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `asgi.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/__main__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/auth/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/auth/context.py` | `ACCOUNT_AWARE` | false | false | true | — |
| `auction_etl/auth/streamlit_auth.py` | `ACCOUNT_AWARE` | false | true | true | — |
| `auction_etl/browser/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/browser/buyee_cdp.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/browser/buyee_owner.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `auction_etl/browser/defaults.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/browser/fetch.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/browser/login.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/browser/manager.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/browser/profiles.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `auction_etl/browser/session.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `auction_etl/classifiers/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/classifiers/media.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/audit.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/browser.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/crawl.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/doctor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/export.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/ingest.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/main.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/normalize.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/parse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/rebuild.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/report.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/review.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cli/stats.py` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `auction_etl/cli/sync.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/cloud_api.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `auction_etl/config/settings.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/crawlers/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/crawlers/buyee.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/crawlers/ebay.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/crawlers/http.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/database/base.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/database/bootstrap.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/database/collector_views.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` |
| `auction_etl/database/health.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/database/session.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `auction_etl/discovery/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/discovery/ebay.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/domain/pressing_reference.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `auction_etl/models/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/models/crawl.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/models/raw.py` | `MANUAL_REVIEW` | false | false | false | `system.crawl_job` |
| `auction_etl/models/staging.py` | `MANUAL_REVIEW` | false | false | false | `raw.page` |
| `auction_etl/models/system.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/models/warehouse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/parser/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/parser/ebay.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/parsers/buyee.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/parsers/ebay.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/reporting/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/reporting/main_review_integration.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.gripsweat_sale` |
| `auction_etl/reporting/recent_ingestion.py` | `MANUAL_REVIEW` | false | false | false | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector_review` |
| `auction_etl/services/account_access.py` | `ACCOUNT_AWARE` | false | false | true | `identity.account`, `identity.account_member`, `identity.app_user` |
| `auction_etl/services/account_scope.py` | `ACCOUNT_AWARE` | false | false | true | `account.auction_listing` |
| `auction_etl/services/artist_tracking.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | — |
| `auction_etl/services/auction_ingest_job.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `auction_etl/services/auction_intake.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `system.auction_pressing_assignment_audit_event`, `system.completeness_cohort_summary`, `system.current_listing_completeness_alert`, `system.listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.new_auction_assignment_queue`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/audit.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/services/cohort_curation_wizard.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `analytics.auction_collector_base`, `system.component_type`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_comparable_review`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/collector_curation.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `analytics.auction_scores`, `analytics.emotional_damage`, `system.component_type`, `system.condition_grade`, `warehouse.auction_analysis_input`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/collector_evidence.py` | `MANUAL_REVIEW` | false | true | false | `analytics.auction_collector_base`, `system.condition_grade`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_price_snapshot` |
| `auction_etl/services/collector_observation_bulk.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `system.evidence_source_registry`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment` |
| `auction_etl/services/completeness_history.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/completeness_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` |
| `auction_etl/services/crawl.py` | `MANUAL_REVIEW` | false | false | false | `raw.id`, `raw.url` |
| `auction_etl/services/dates.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/services/deterministic_verdicts.py` | `MANUAL_REVIEW` | false | true | false | `analytics.auction_alerts`, `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.emotional_damage`, `analytics.midfication_detection`, `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `warehouse.auction`, `warehouse.auction_completeness` |
| `auction_etl/services/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `auction_etl/services/export.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/services/fx.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/services/ingest.py` | `MANUAL_REVIEW` | false | false | false | `raw.id` |
| `auction_etl/services/media_aware_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `system.evidence_source_registry`, `system.media_profile_component`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/media_profile_admin.py` | `MANUAL_REVIEW` | false | false | false | `system.component_type`, `system.media_profile_audit_event`, `system.media_profile_component`, `warehouse.pressing_identity` |
| `auction_etl/services/normalization_readiness.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `analytics.auction_collector_base`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation` |
| `auction_etl/services/normalization_workbench.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `analytics.auction_collector_base`, `analytics.normalization_work_queue`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_comparable_review`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/normalize.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/services/parse.py` | `MANUAL_REVIEW` | false | false | false | `raw.html`, `raw.id`, `raw.listing_count`, `raw.parsed_at`, `raw.source` |
| `auction_etl/services/pressing_reference_admin.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/pressing_reference_catalog.py` | `MANUAL_REVIEW` | false | false | false | `system.reference_audit_event`, `warehouse.pressing_identity`, `warehouse.pressing_matrix_runout`, `warehouse.pressing_reference_catalog`, `warehouse.release_family` |
| `auction_etl/services/pressing_reference_workbench.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/reference_record_admin.py` | `MANUAL_REVIEW` | false | true | false | `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.component_type`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` |
| `auction_etl/services/refresh_jobs.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace` |
| `auction_etl/services/report.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/services/review.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/services/state_safe_completeness.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `system.component_type`, `system.media_profile_component`, `warehouse.auction`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `auction_etl/services/warehouse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/urls/__init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/urls/buyee.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/urls/ebay.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `auction_etl/urls/router.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/alembic-env-repair-20260801-225102/env.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/collector-analytics-editor-20260802-121838/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/collector-evidence-20260802-222200/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/completeness-reference-editor-20260802-235534/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/completeness-reference-finish-v2-20260803-000050/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/completeness-reference-finish-v2-20260803-000050/completeness_reference.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `warehouse.pressing_identity` |
| `backups/completeness-reference-finish-v2-20260803-000050/test_collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/completeness-reference-finish-v2-20260803-000050/test_completeness_reference.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/completeness-reference-finish-v3-20260803-000323/test_collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/completeness-reference-finish-v4-20260803-000838/test_collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/completeness-reference-test-fix-20260802-235759/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/completeness-reference-test-fix-20260802-235759/completeness_reference.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `warehouse.pressing_identity` |
| `backups/completeness-reference-test-fix-20260802-235759/test_collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/completeness-reference-test-fix-20260802-235759/test_completeness_reference.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/config-repair-20260801-223019/auction_etl/config/settings.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/config-repair-20260801-223019/auction_etl/database/session.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `backups/factory-sealed-autofill-resume-20260803-002517/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/factory-sealed-autofill-resume-20260803-002517/completeness_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` |
| `backups/factory-sealed-autofill-resume-20260803-002517/test_factory_sealed_completeness.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/factory-sealed-autofill-resume-20260803-002717/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/factory-sealed-autofill-resume-20260803-002717/completeness_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` |
| `backups/factory-sealed-autofill-resume-20260803-002717/test_factory_sealed_completeness.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/factory-sealed-autofill-resume-20260803-101821/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/factory-sealed-autofill-resume-20260803-101821/completeness_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` |
| `backups/factory-sealed-autofill-resume-20260803-101821/test_factory_sealed_completeness.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/factory-sealed-completeness-20260803-002133/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/factory-sealed-completeness-20260803-002133/completeness_reference.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `warehouse.pressing_identity` |
| `backups/general-reference-workbench-finish-20260803-145638/app_pages_2_Completeness_Reference.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `backups/general-reference-workbench-finish-20260803-145638/auction_etl_services_pressing_reference_workbench.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `backups/general-reference-workbench-finish-20260803-145638/tests_test_pressing_reference_workbench.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/general-reference-workbench-finish-20260803-145638/tests_test_pressing_reference_workbench_page.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/generated-behavior-fix-20260802-213622/collector_curation.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `analytics.auction_scores`, `analytics.emotional_damage`, `system.component_type`, `system.condition_grade`, `warehouse.auction_analysis_input`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `backups/generated-behavior-v2-20260802-214618/collector_curation.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `analytics.auction_scores`, `analytics.emotional_damage`, `system.component_type`, `system.condition_grade`, `warehouse.auction_analysis_input`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `backups/generated-behavior-v2-20260802-214618/curate-q1236919590.py` | `MANUAL_REVIEW` | true | false | false | `warehouse.auction` |
| `backups/historical-anchor-guard-20260802-230052/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/historical-anchor-guard-20260802-230052/collector_evidence.py` | `MANUAL_REVIEW` | false | true | false | `system.condition_grade`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_price_snapshot` |
| `backups/historical-anchor-guard-resume-20260802-231131/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/historical-anchor-guard-resume-20260802-231131/collector_evidence.py` | `MANUAL_REVIEW` | false | true | false | `system.condition_grade`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_price_snapshot` |
| `backups/historical-anchor-guard-v3-20260802-231840/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/historical-anchor-guard-v3-20260802-231840/collector_evidence.py` | `MANUAL_REVIEW` | false | true | false | `system.condition_grade`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_price_snapshot` |
| `backups/pressing-reference-search-fix-20260803-111313/pressing_reference_admin.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `backups/pressing-reference-search-fix-20260803-111313/test_pressing_reference_admin.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/pressing-reference-workbench-20260803-140751/2_Completeness_Reference.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `backups/private/runtime-scripts/collector-export-ui-20260801-095114/README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `backups/private/runtime-scripts/collector-export-ui-20260801-095114/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/collector-hover-click-20260731-215531/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/collector-hover-click-20260731-215531/pyproject.toml` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-223948/README.md` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-223948/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-223948/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-223948/pyproject.toml` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-223948/tests/test_collector_hover_click_grid.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-223948/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/pyproject.toml` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/scripts/accept_collector_hover_click.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/tests/test_collector_hover_click_acceptance_source.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/tests/test_collector_hover_click_grid.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-224656/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/pyproject.toml` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/scripts/accept_collector_hover_click.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/tests/test_collector_hover_click_acceptance_source.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/tests/test_collector_hover_click_grid.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-hover-click-finalize-20260731-225122/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-review-recovery-20260727-165333/collector_features.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/pyproject.toml` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/scripts/accept_collector_hover_click.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/tests/test_collector_hover_click_acceptance_source.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/tests/test_collector_hover_click_grid.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-save-repair-20260731-230406/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/collector-view-20260727-155914/collector_features.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `backups/private/runtime-scripts/collector-view-20260727-155914/sync.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-view-20260727-155914/warehouse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-view-final-20260727-161510/collector_features.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `backups/private/runtime-scripts/collector-view-final-20260727-161510/sync.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-view-final-20260727-161510/warehouse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/collector-view-owner-20260728-095124/scripts_collector_features.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `backups/private/runtime-scripts/dict-row-fix-20260730-144916/inspect_recent_ingestion.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.auction` |
| `backups/private/runtime-scripts/dict-row-fix-20260730-144916/run_latest_auction_refresh.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.gripsweat_sale` |
| `backups/private/runtime-scripts/duplicate-columns-20260731-142908/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/duplicate-columns-20260731-142908/auction_etl/reporting/main_review_integration.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.gripsweat_sale` |
| `backups/private/runtime-scripts/export-ui-fix-20260801-095704/README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `backups/private/runtime-scripts/export-ui-fix-20260801-095704/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/helper-relocation-20260731-143250/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/helper-relocation-20260731-143250/auction_etl/reporting/main_review_integration.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.gripsweat_sale` |
| `backups/private/runtime-scripts/helper-relocation-20260731-143250/tests/test_duplicate_dataframe_columns.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-154805/app_pages_3_Latest_Auction_Refresh.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-154805/scripts_inspect_recent_ingestion.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.auction` |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/app_pages_3_Latest_Auction_Refresh.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/auction_etl_reporting___init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/auction_etl_reporting_recent_ingestion.py` | `MANUAL_REVIEW` | false | false | false | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/config_report_media_types.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/scripts_hard_test_latest_refresh_ui.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/scripts_inspect_recent_ingestion.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/scripts_launch_latest_refresh_job.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/scripts_update_ingestion_audit.py` | `MANUAL_REVIEW` | true | false | false | `system.auction_ingestion_identity` |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/tests_test_latest_refresh_ui_source.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/tests_test_recent_ingestion_reporting.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/latest-reporting-20260730-161847/tests_test_safe_sync_contract.py` | `MANUAL_REVIEW` | false | true | false | `warehouse.py` |
| `backups/private/runtime-scripts/latest-reporting-finalize-20260730-164007/auction_etl_database_collector_views.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` |
| `backups/private/runtime-scripts/latest-reporting-finalize-20260730-164007/auction_etl_reporting___init__.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/latest-reporting-finalize-20260730-164007/auction_etl_reporting_recent_ingestion.py` | `MANUAL_REVIEW` | false | false | false | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/latest-reporting-finalize-20260730-164007/tests_test_recent_ingestion_reporting.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/live-ui-repair-20260730-185406/app_collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/main-integration-20260730-195442/app_collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/main-integration-20260730-195442/app_pages_4_Recent_Buyee_Additions.py` | `MANUAL_REVIEW` | true | true | false | `system.auction_ingestion_identity`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/main-integration-20260730-195442/tests_test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/pagination-key-20260730-190407/app_collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/pagination-key-20260730-190407/app_pages_4_Recent_Buyee_Additions.py` | `MANUAL_REVIEW` | true | true | false | `system.auction_ingestion_identity`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/pagination-key-20260730-190407/tests_test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/recent-export-20260801-155634/README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `backups/private/runtime-scripts/recent-export-20260801-155634/collector_export.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/recent-export-20260801-155634/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/restore-port-5544-20260801-140934/README.md` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction_collector` |
| `backups/private/runtime-scripts/restore-port-5544-20260801-140934/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/review-toc-20260727-170916/collector_features.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` |
| `backups/private/runtime-scripts/safe-sync-20260727-143533/sync.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/safe-sync-20260727-143533/warehouse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/safe-sync-continuation-20260727-144115/sync.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/safe-sync-continuation-20260727-144115/warehouse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/safe-sync-finalize-20260727-144628/sync.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/safe-sync-finalize-20260727-144628/warehouse.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/selection-redesign-20260731-162928/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/selection-redesign-20260731-162928/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/selection-redesign-20260731-162928/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165210/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165210/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165210/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165811/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165811/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-165811/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-173808/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-173808/app/collector_review_support.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/selection-redesign-continuation-20260731-173808/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/source-aware-20260731-100903/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/source-aware-20260731-100903/auction_etl/reporting/main_review_integration.py` | `MANUAL_REVIEW` | true | false | false | `system.auction_ingestion_identity` |
| `backups/private/runtime-scripts/source-aware-20260731-100903/scripts/crawl_buyee_live_details.py` | `MANUAL_REVIEW` | false | true | false | `warehouse.auction`, `warehouse.auction_detail` |
| `backups/private/runtime-scripts/source-aware-20260731-100903/tests/test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/source-aware-20260731-100903/tests/test_main_review_recent_integration.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `backups/private/runtime-scripts/streamlit-width-20260731-152713/app/collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/streamlit-width-20260731-152713/app/pages/3_Latest_Auction_Refresh.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `backups/private/runtime-scripts/update-status-20260730-191418/app_collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/update-status-20260730-191418/app_pages_4_Recent_Buyee_Additions.py` | `MANUAL_REVIEW` | true | true | false | `system.auction_ingestion_identity`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/update-status-20260730-191418/tests_test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/private/runtime-scripts/update-status-v2-20260730-192538/app_collector_review.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/update-status-v2-20260730-192538/app_pages_4_Recent_Buyee_Additions.py` | `MANUAL_REVIEW` | true | true | false | `system.auction_ingestion_identity`, `warehouse.auction_collector_review` |
| `backups/private/runtime-scripts/update-status-v2-20260730-192538/tests_test_live_collector_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `backups/reference-record-audit-20260803-155517/3_Evidence_and_Bulk_Observations.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `config/ebay_sources.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `config/gripsweat_sources.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `config/report_media_types.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `docs/ACCOUNT_DATA_OWNERSHIP.md` | `DOCUMENTATION` | false | false | true | `account.auction_listing`, `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_pressing_assignment` |
| `docs/ACCOUNT_SCOPING_MATRIX.md` | `DOCUMENTATION` | false | false | false | — |
| `docs/ARCHITECTURE.md` | `DOCUMENTATION` | false | true | false | `ops.refresh_job`, `ops.refresh_marketplace`, `system.auction_pressing_assignment_audit_event`, `system.current_listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment` |
| `docs/DATABASE_DEPLOYMENT.md` | `DOCUMENTATION` | true | false | false | `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace` |
| `docs/DEPLOYMENT.md` | `DOCUMENTATION` | true | false | false | — |
| `docs/PHASE_D_AUTH_ACCOUNT_ARCHITECTURE.md` | `DOCUMENTATION` | false | false | true | `account.artist_marketplace`, `account.auction_listing`, `account.tracked_artist`, `identity.app_user`, `ops.refresh_job`, `warehouse.auction` |
| `docs/PHASE_D_MIGRATION_RUNBOOK.md` | `DOCUMENTATION` | false | true | true | `account.artist_marketplace`, `account.auction_listing`, `account.tracked_artist` |
| `docs/PHASE_D_SECURITY_MODEL.md` | `DOCUMENTATION` | false | false | true | `identity.account`, `identity.account_member`, `identity.app_user` |
| `docs/PHASE_D_TEST_PLAN.md` | `DOCUMENTATION` | false | true | false | — |
| `docs/collector-analytics-model.md` | `DOCUMENTATION` | false | true | false | — |
| `exports/auctions.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/auctions.md` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/listings.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/listings.md` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260730-145812/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260815-102910/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260815-142513/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260815-165509/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260815-202814/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260815-234936/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260816-143944/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260816-153544/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260816-181929/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260816-205929/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260818-125949/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260818-155612/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260818-173118/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260819-145322/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `exports/new-only/20260819-214124/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/1238164700/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/b1237947373/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/c1237065379/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/c1238187152/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/c1238781354/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/d1154821939/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/d1237025928/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/e1233866479/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/e1236425973/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/e1237375957/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/e1237556358/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/e1238051623/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/e1238146832/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/e1238299583/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/f1238039300/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/f1238144486/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/g1237869070/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/g1238141114/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/h1237093190/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/h1237780645/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/h1238109498/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/h1238629945/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/j1237279765/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/j1237658047/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/j1238038255/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/j1238300758/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/k1236724385/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/k1237466839/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/l1237102758/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/m1211540259/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/n1234140391/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/n1237558802/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/o1237096076/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/o1237440513/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/o1237655029/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/o1238154141/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/o1238644452/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/p1237662482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/p1237767268/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/p1237918961/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/q1236919590/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/r1236013861/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/r1237116994/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/r1237541872/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/r1238300627/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/s1237683502/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/s1238137759/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/t1237552062/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/t1237959074/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/u1236757760/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/u1237666927/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/u1237902459/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/u1237995599/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/u1238043564/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/u1238068130/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/v1237568706/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/w1236812667/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/w1238402476/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/x1177145102/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/x1237176176/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/detail-enrichment/20260731-101727/crawler/x1238110782/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/1232634180/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/1235984736/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/1236211414/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/1236385101/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/1237431592/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/b1223131324/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/b1237047277/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/c1236824677/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/c1236830803/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/d1235934591/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/d1236498357/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/d1237188926/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/e1235663080/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/e1235762972/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/e1235903299/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/e1236587150/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/e1236829186/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/e1237586209/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/f1231273405/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/f1235876746/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/f1235897477/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/g1235528718/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/g1235793474/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/g1236156344/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/g1236248266/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/g1236409017/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/g1236813289/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/h1233945027/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/h1236591732/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/h1236712838/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/j1234069328/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/j1234230655/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/j1236801757/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/k1231396804/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/k1235571266/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/k1235990465/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/k1236392950/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/k1237054349/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/k1237222814/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/l1233927355/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/m1204167085/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/m1235836525/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/n1233656215/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/n1236385465/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/o1236827123/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/p1216738288/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/p1235809752/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/p1236718241/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/p1236985064/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/p1237438598/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/r1222204540/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/r1233145181/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/r1235773038/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/r1235803458/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/r1236396150/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/s1236394712/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/s1236404682/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/t1231755324/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/t1236383360/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/t1237232894/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/u1235112020/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/u1235796070/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/u1236338996/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/u1237049864/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/u1237347970/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/v1234437477/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/v1235791596/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/v1235799886/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/v1235825104/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/v1236494066/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/v1237048166/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/w1235790438/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/w1236815482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/x1235978230/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/x1235997626/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/x1236376791/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/apply/x1236414551/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/dry-run/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/dry-run/w1236815482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/dry-run/x1235978230/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/dry-run/x1235997626/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/dry-run/x1236376791/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/host-refresh-20260726-182718/dry-run/x1236414551/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail/w1236815482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail/x1235978230/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail/x1235997626/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail/x1236376791/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail/x1236414551/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/1232634180/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/1235984736/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/1236211414/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/1236385101/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/1237431592/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/b1223131324/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/b1237047277/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/c1236824677/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/c1236830803/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/d1235934591/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/d1236498357/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/d1237188926/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/e1235663080/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/e1235762972/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/e1235903299/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/e1236587150/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/e1236829186/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/e1237586209/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/f1231273405/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/f1235876746/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/f1235897477/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/g1235528718/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/g1235793474/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/g1236156344/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/g1236248266/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/g1236409017/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/g1236813289/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/h1233945027/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/h1236591732/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/h1236712838/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/j1234069328/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/j1234230655/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/j1236801757/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/k1231396804/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/k1235571266/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/k1235990465/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/k1236392950/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/k1237054349/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/k1237222814/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/l1233927355/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/m1204167085/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/m1235836525/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/n1233656215/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/n1236385465/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/o1236827123/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/p1216738288/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/p1235809752/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/p1236718241/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/p1236985064/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/p1237438598/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/r1222204540/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/r1233145181/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/r1235773038/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/r1235803458/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/r1236396150/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/s1236394712/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/s1236404682/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/t1231755324/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/t1236383360/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/t1237232894/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/u1235112020/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/u1235796070/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/u1236338996/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/u1237049864/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/u1237347970/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/v1234437477/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/v1235791596/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/v1235799886/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/v1235825104/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/v1236494066/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/v1237048166/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/w1235790438/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/w1236815482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/x1235978230/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/x1235997626/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/x1236376791/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/apply/x1236414551/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/dry-run/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/dry-run/w1236815482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/dry-run/x1235978230/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/dry-run/x1235997626/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/dry-run/x1236376791/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/live-detail-20260725-011110/dry-run/x1236414551/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/patient-session-20260730-140909/candidate-links.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/session-refresh-20260730-115556/candidate-links.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee/session-refresh-20260730-140116/candidate-links.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee_detail_probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/buyee_detail_probe_newest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/canonical-media-reference-20260804-171444/source-before-install/2_Completeness_Reference.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/canonical-media-reference-20260804-172334/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/canonical-media-reference-20260804-172334/source-before-install/2_Completeness_Reference.py` | `MANUAL_REVIEW` | true | true | false | `identity.get` |
| `logs/colima-fixed-port-20260805-162941/compose-config.json` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `logs/colima-only-ebay-crawl-20260806-185844/cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/colima-only-ebay-crawl-20260806-185844/source-config-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/collector-analytics-browser-20260802-183849/report.json` | `MANUAL_REVIEW` | false | false | false | `analytics.png` |
| `logs/collector-evidence-20260802-222200/apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/collector-evidence-20260802-222200/dry-run.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/collector-hover-click/20260731-215531/headed_browser_acceptance.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/collector-save-repair/20260731-230406/browser/acceptance.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/collector-view-owner/source-drift-20260728-100946/collector_features.evidence.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `logs/collector-view-ownership/20260727-171739/auction_collector_effective.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector` |
| `logs/collector-view-ownership/20260727-171739/auction_collector_review.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `logs/collector-view-ownership/20260727-171739/collector_features.c80774e.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `logs/collector-view-ownership/20260727-172854/auction_collector_effective.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector` |
| `logs/collector-view-ownership/20260727-172854/auction_collector_review.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `logs/collector-view-ownership/20260727-172854/collector_features.c80774e.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `logs/collector-view-ownership/20260727-173819/auction_collector_effective.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector` |
| `logs/collector-view-ownership/20260727-173819/auction_collector_review.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `logs/collector-view-ownership/20260727-173819/collector_features.c80774e.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `logs/collector-view-recovery/20260727-165333/auction_collector_review.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/collector-view-recovery/toc-20260727-170916/auction_collector_review.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` |
| `logs/collector-view-repair/final-20260727-161510/managed-views-before.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail` |
| `logs/completeness-history-identity-fix-20260804-214023/before-fix/auction_etl/services/completeness_history.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` |
| `logs/completeness-history-identity-fix-20260804-214023/before-fix/scripts/accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-history-identity-fix-20260804-214023/before-fix/tests/test_accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-history-identity-fix-20260804-214023/before-fix/tests/test_completeness_history.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.listing_completeness_snapshot` |
| `logs/completeness-history-identity-fix-20260804-214023/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/completeness-history-import-fix-20260804-191249/before-fix/accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-history-import-fix-20260804-191249/before-fix/test_accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-history-selector-20260804-191017/before-fix/accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-history-selector-20260804-191017/before-fix/test_accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/completeness-installer-page-contract-20260804-185056/before-fix/10_Listing_Completeness_Review.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline_down.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.completeness_changed_fields`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_component`, `system.reject_completeness_snapshot_mutation`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation` |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/alembic/versions/d4e8b1c7a903_completeness_snapshots_and_timeline_up.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.completeness_changed_fields`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_component`, `system.reject_completeness_snapshot_mutation`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/app/pages/10_Listing_Completeness_Review.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/app/pages/12_Completeness_History.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/auction_etl/services/completeness_history.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity` |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/scripts/accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/tests/test_accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/tests/test_completeness_history.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.listing_completeness_snapshot` |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/tests/test_completeness_history_migration.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment` |
| `logs/completeness-rowtype-recovery-20260804-190446/failed-run-backup/tests/test_completeness_history_page.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/completeness-snapshot-contract-20260804-182919/contract.json` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `system.capture_media_profile_audit`, `system.capture_reference_audit`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_audit_event`, `system.media_profile_audit_event_id_seq`, `system.media_profile_component`, `system.normalization_work_audit_event`, `system.normalization_work_audit_event_id_seq`, `system.reference_audit_event`, `system.reference_audit_event_id_seq`, `system.reject_media_profile_audit_mutation`, `system.reject_reference_audit_mutation`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_component_observation_id_seq`, `warehouse.auction_id_seq`, `warehouse.auction_pressing_assignment`, `warehouse.auction_pressing_assignment_id_seq`, `warehouse.pressing_component_expectation`, `warehouse.pressing_component_expectation_id_seq`, `warehouse.pressing_identity`, `warehouse.pressing_identity_id_seq` |
| `logs/component-registry-discovery-20260804-130403/mr2276-review/packet-review-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/component-registry-discovery-20260804-130403/pending-before-fix/review_and_apply_pressing_packet.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.component_type`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/component-registry-discovery-20260804-130403/pending-before-fix/test_review_and_apply_pressing_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/curation-queue-20260802-224215/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/current-db-rebuild-20260805-143820/container-inspect.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-165956/containers/colima.json` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/docker-context-audit-20260805-171546/metadata-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-171655/metadata-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-200527/metadata-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-200539/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-201404/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-201417/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-201834/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-201931/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-205915/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-210910/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-211723/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-212840/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-233912/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-234503/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260805-234536/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-132332/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-174028/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-183708/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-184314/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-184528/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-184917/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-185847/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-190025/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-190624/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-200509/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260806-201353/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/docker-context-audit-20260807-135239/metadata-assert-clean.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ebay/sync-repair-20260727-122424/inspect.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ebay/sync-repair-20260727-122424/repair.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction`, `warehouse.uq_auction_marketplace_listing` |
| `logs/ebay/sync-repair-20260727-122424/verify.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/ebay-source-cohort-20260805-230400/cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ebay-source-cohort-20260805-230812/cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ebay-source-cohort-20260805-230812/create-source-view.sql` | `MANUAL_REVIEW` | false | false | false | `raw.page` |
| `logs/ebay-source-cohort-20260805-230812/selected-candidate.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/emotional-damage-contract-20260802-214814/auction-alerts-view.sql` | `MANUAL_REVIEW` | false | false | false | `analytics.auction_collector_base`, `analytics.completeness_premium` |
| `logs/emotional-damage-contract-20260802-214814/auction-scores-view.sql` | `MANUAL_REVIEW` | false | false | false | `analytics.auction_collector_base` |
| `logs/emotional-damage-contract-20260802-214814/emotional-damage-view.sql` | `MANUAL_REVIEW` | false | false | false | `analytics.auction_collector_base`, `analytics.auction_scores` |
| `logs/evidence-handoff-proven-navigation-20260804-151743/pending-before-navigation-fix/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/evidence-handoff-proven-navigation-20260804-151743/pending-before-navigation-fix/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/evidence-handoff-proven-navigation-20260804-151743/pending-before-navigation-fix/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-proven-navigation-20260804-151743/pending-before-navigation-fix/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/evidence-handoff-proven-navigation-20260804-151743/pending-before-navigation-fix/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-proven-navigation-20260804-151743/pending-before-navigation-fix/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-proven-navigation-20260804-151743/proven-navigator-control/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/evidence-handoff-route-fix-20260804-150646/pending-before-route-fix/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/evidence-handoff-route-fix-20260804-150646/pending-before-route-fix/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/evidence-handoff-route-fix-20260804-150646/pending-before-route-fix/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-route-fix-20260804-150646/pending-before-route-fix/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/evidence-handoff-route-fix-20260804-150646/pending-before-route-fix/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-route-fix-20260804-150646/pending-before-route-fix/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-test-fix-20260804-151114/pending-before-test-fix/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/evidence-handoff-test-fix-20260804-151114/pending-before-test-fix/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/evidence-handoff-test-fix-20260804-151114/pending-before-test-fix/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-test-fix-20260804-151114/pending-before-test-fix/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/evidence-handoff-test-fix-20260804-151114/pending-before-test-fix/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-handoff-test-fix-20260804-151114/pending-before-test-fix/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/evidence-source-key-repair-20260803-172246/migration-source-key-repair.sql` | `MANUAL_REVIEW` | false | false | false | `system.evidence_source_registry`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation` |
| `logs/explicit-handoff-finish-20260804-162456/pending-before-finish/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-162456/pending-before-finish/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-162456/pending-before-finish/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-162456/pending-before-finish/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/explicit-handoff-finish-20260804-162456/pending-before-finish/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-162456/pending-before-finish/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-162838/pending-before-finish/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-162838/pending-before-finish/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-162838/pending-before-finish/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-162838/pending-before-finish/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/explicit-handoff-finish-20260804-162838/pending-before-finish/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-162838/pending-before-finish/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-163110/pending-before-finish/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-163110/pending-before-finish/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-163110/pending-before-finish/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-163110/pending-before-finish/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/explicit-handoff-finish-20260804-163110/pending-before-finish/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-163110/pending-before-finish/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-163411/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/explicit-handoff-finish-20260804-163411/pending-before-finish/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-163411/pending-before-finish/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-handoff-finish-20260804-163411/pending-before-finish/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-163411/pending-before-finish/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/explicit-handoff-finish-20260804-163411/pending-before-finish/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-handoff-finish-20260804-163411/pending-before-finish/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152445/pending-before-fix/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152445/pending-before-fix/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152445/pending-before-fix/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152445/pending-before-fix/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/explicit-wizard-cohort-handoff-20260804-152445/pending-before-fix/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152445/pending-before-fix/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152828/pending-before-fix/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152828/pending-before-fix/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152828/pending-before-fix/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152828/pending-before-fix/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/explicit-wizard-cohort-handoff-20260804-152828/pending-before-fix/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/explicit-wizard-cohort-handoff-20260804-152828/pending-before-fix/test_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/fix-provenance-schema-20260808-193839/schema-contract.json` | `MANUAL_REVIEW` | false | false | false | `raw.page`, `system.crawl_job`, `warehouse.auction` |
| `logs/fresh-facerecords-crawl-20260808-205027/selected-source.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/fresh-facerecords-crawl-20260808-205945/selected-source.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/fresh-facerecords-crawl-20260808-213656/selected-source.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/general-evidence-intake-20260804-133417/filesystem-smoke/generic-packet/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/general-evidence-intake-20260804-133417/filesystem-smoke/generic-packet/packet-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/general-evidence-intake-20260804-133417/pending-before-install/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/general-evidence-intake-20260804-133417/pending-before-install/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/general-evidence-intake-20260804-133417/pending-before-install/test_evidence_intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/general-evidence-intake-20260804-133417/pending-before-install/test_evidence_intake_page.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/generated-behavior-v2-20260802-214618/behavior-upsert-after.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/generated-behavior-v2-20260802-214618/behavior-upsert-before.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/generated-behavior-v2-20260802-214618/curation-result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/global-component-review-20260802-234854/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/gripsweat/pagination-audit/gripsweat_pagination_audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/gripsweat/probe/gripsweat_probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/handoff-catalog-fallback-20260804-163408/before-fallback/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/handoff-catalog-fallback-20260804-163408/before-fallback/test_accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/historical-anchor-guard-20260802-230052/before.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/historical-anchor-guard-v3-20260802-231840/apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/historical-anchor-guard-v3-20260802-231840/dry-run.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/historical-anchor-guard-verification-20260802-232722/dry-run.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingest-assignment-queue-20260805-184448/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingest-assignment-queue-20260805-203004/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-192151/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-192151/source-refresh-state/runs/20260814-152155/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-192151/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-200009/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-200009/source-refresh-state/runs/20260814-160012/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-200009/source-refresh-state/runs/20260814-160012/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-200009/source-refresh-state/runs/20260814-160012/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260814-200009/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-020410/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-020410/source-refresh-state/runs/20260814-220411/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-020410/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-033431/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-033431/source-refresh-state/runs/20260814-233433/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-033431/source-refresh-state/runs/20260814-233433/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-033431/source-refresh-state/runs/20260814-233433/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-033431/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-040533/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-040533/source-refresh-state/runs/20260815-000534/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-040533/source-refresh-state/runs/20260815-000534/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-040533/source-refresh-state/runs/20260815-000534/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-040533/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-142908/source-refresh-state/runs/20260815-102910/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-142908/source-refresh-state/runs/20260815-102910/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-142908/source-refresh-state/runs/20260815-102910/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-142908/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-182510/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-182510/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-182510/source-refresh-state/runs/20260815-142513/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-182510/source-refresh-state/runs/20260815-142513/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-182510/source-refresh-state/runs/20260815-142513/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-182510/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-205507/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-205507/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-205507/source-refresh-state/runs/20260815-165509/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-205507/source-refresh-state/runs/20260815-165509/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-205507/source-refresh-state/runs/20260815-165509/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260815-205507/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-002811/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-002811/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-002811/source-refresh-state/runs/20260815-202814/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-002811/source-refresh-state/runs/20260815-202814/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-002811/source-refresh-state/runs/20260815-202814/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-002811/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-034933/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-034933/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-034933/source-refresh-state/runs/20260815-234936/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-034933/source-refresh-state/runs/20260815-234936/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-034933/source-refresh-state/runs/20260815-234936/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-034933/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-183941/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-183941/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-183941/source-refresh-state/runs/20260816-143944/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-183941/source-refresh-state/runs/20260816-143944/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-183941/source-refresh-state/runs/20260816-143944/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-183941/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-193543/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-193543/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-193543/source-refresh-state/runs/20260816-153544/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-193543/source-refresh-state/runs/20260816-153544/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-193543/source-refresh-state/runs/20260816-153544/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-193543/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-205309/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-205309/source-refresh-state/runs/20260816-165311/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-205309/source-refresh-state/runs/20260816-165311/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-205309/source-refresh-state/runs/20260816-165311/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-205309/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-221926/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-221926/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-221926/source-refresh-state/runs/20260816-181929/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-221926/source-refresh-state/runs/20260816-181929/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260816-221926/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260817-005928/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260817-005928/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260817-005928/source-refresh-state/runs/20260816-205929/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260817-005928/source-refresh-state/runs/20260816-205929/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260817-005928/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-152036/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-152036/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1232634180/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1235984736/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1236211414/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1236385101/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1237431592/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1238164700/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1239092128/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/1239481497/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/b1223131324/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/b1237047277/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/b1237947373/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/b1238581945/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/b1238957482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/b1239234570/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/b1239947791/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1236824677/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1236830803/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1237065379/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1238187152/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1238781354/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1238795482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1238975737/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1238980556/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1240411671/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/c1240534269/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1154821939/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1235934591/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1236498357/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1237025928/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1237188926/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1238801271/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1239104593/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1239258701/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1239864376/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/d1240511524/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1233866479/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1235663080/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1235762972/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1235903299/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1236425973/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1236587150/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1236829186/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1237375957/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1237556358/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1237586209/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1238051623/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1238146832/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1238299583/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1238777629/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1238966488/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/e1239107718/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/f1231273405/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/f1235876746/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/f1235897477/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/f1238039300/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/f1238144486/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1235528718/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1235793474/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1236156344/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1236248266/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1236409017/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1236813289/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1237869070/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1238141114/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/g1239032090/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1233945027/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1236591732/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1236712838/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1237093190/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1237780645/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1238109498/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1238629945/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1238965102/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1239168736/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1239405206/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/h1240528868/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1234069328/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1234230655/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1236801757/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1237279765/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1237658047/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1238038255/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1238299842/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1238300758/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1239531113/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1240068849/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/j1240393407/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1231396804/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1235571266/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1235990465/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1236392950/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1236724385/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1237054349/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1237222814/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1237466839/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1238954257/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1239493925/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1240075862/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/k1240534703/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/l1227207408/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/l1233927355/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/l1237102758/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/l1240090870/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/l1240391188/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/l1240405804/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/l1240411573/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1204167085/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1211540259/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1231135196/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1235836525/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1236944618/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1238967273/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1239247463/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1239338721/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1239349714/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1240421616/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/m1240717097/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/n1233656215/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/n1234140391/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/n1236385465/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/n1237558802/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/n1238959538/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/n1239257640/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/n1239712863/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1236827123/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1237096076/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1237440513/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1237655029/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1238154141/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1238644452/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1239335544/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1239388405/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/o1240405013/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1216738288/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1235809752/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1236718241/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1236985064/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1237438598/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1237662482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1237767268/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1237918961/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1238861259/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1238903191/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/p1240390189/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/q1236919590/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/q1238768455/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/q1238949046/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/q1239304819/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/q1239861003/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/q1239879221/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/q1240066343/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1222204540/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1233145181/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1233195301/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1235773038/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1235803458/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1236013861/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1236396150/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1237116994/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1237541872/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/r1238300627/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1233282459/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1236394712/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1236404682/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1237683502/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1238137759/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1238924405/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1239256246/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1239491329/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1239559092/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/s1240859158/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1231755324/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1236383360/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1237232894/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1237552062/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1237959074/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1238701778/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1239960967/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1240083650/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1240149102/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/t1240179094/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1235112020/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1235796070/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1236338996/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1236757760/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1237049864/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1237347970/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1237666927/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1237902459/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1237995599/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1238043564/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1238068130/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/u1238911914/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1167726543/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1234437477/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1235776295/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1235791596/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1235799886/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1235825104/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1236494066/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1236792216/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1237048166/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1237568706/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1238788626/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1239246810/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1239607705/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/v1240950101/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/w1235790438/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/w1236812667/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/w1236815482/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/w1238402476/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/w1238901759/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/w1240610272/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/w1240676814/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1177145102/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1235978230/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1235997626/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1236376791/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1236414551/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1237176176/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1238110782/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1238758214/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1239622619/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1239850643/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/buyee-details/x1240518796/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/runs/20260818-125949/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-165946/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-192813/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-192813/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-195610/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-195610/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-195610/source-refresh-state/runs/20260818-155612/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-195610/source-refresh-state/runs/20260818-155612/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-195610/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-213115/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-213115/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-213115/source-refresh-state/runs/20260818-173118/ebay-incremental-facerecords.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-213115/source-refresh-state/runs/20260818-173118/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-213115/source-refresh-state/runs/20260818-173118/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260818-213115/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/pressing-reference-evidence.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/1173553079/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/crawl_summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/d1240524591/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/e1240505427/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/f1239993285/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/g1240528739/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/g1240538391/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/h1240711431/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/j1240542245/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/k1217853013/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/k1240504882/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/p1232793940/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/q1240540805/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/s1240728902/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/u1240874684/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/v1240937538/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/w1240717003/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/buyee-details/x1240775350/detail.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/ebay-incremental-facerecords.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/gripsweat-detail-apply.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/gripsweat-pagination-audit.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/runs/20260819-214124/gripsweat-probe.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round/multisource-20260820-014121/source-refresh-state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260810-200121/fake-tools/fake_audit.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260810-200121/fake-tools/fake_inspector.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260810-200121/fake-tools/fake_runner.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-000332/fake-tools/fake_audit.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-000332/fake-tools/fake_inspector.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-000332/fake-tools/fake_runner.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-000332/state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-000332/state/ui-20260811-000338-74878/ingestion-round/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-152955/fake-tools/fake_audit.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-152955/fake-tools/fake_inspector.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-152955/fake-tools/fake_runner.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-152955/state/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ingestion-round-ui-test/20260811-152955/state/ui-20260811-153007-95979/ingestion-round/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/latest-refresh/buyee-auth.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/latest-refresh/status.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/live-ingest-20260805-151928/wrapper/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/media-aware-reference-contract-20260804-170108/contract.json` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.bulk_observation_batch_row`, `system.component_type`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_component_expectation_id_seq`, `warehouse.pressing_identity`, `warehouse.pressing_identity_id_seq`, `warehouse.release_family` |
| `logs/media-profile-page-contract-fix-20260804-174717/before-fix/11_Media_Profile_Admin.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/media-profile-page-contract-fix-20260804-174717/before-fix/test_state_safe_completeness_and_media_profile_pages.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/media-profile-static-validation-fix-20260804-174354/before-fix/media_profiles_and_state_safe_completeness_up.sql` | `MANUAL_REVIEW` | false | false | false | `system.capture_media_profile_audit`, `system.component_type`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.reject_media_profile_audit_mutation` |
| `logs/media-profile-warning-indent-fix-20260804-180425/before-fix/11_Media_Profile_Admin.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/media-profile-warning-indent-fix-20260804-180425/before-fix/test_state_safe_completeness_and_media_profile_pages.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/media-reference-quantity-fix-20260804-172326/before-fix/media_aware_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/media-reference-quantity-fix-20260804-172326/before-fix/test_media_aware_reference.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type` |
| `logs/missing-ebay-source-diagnostic-20260805-214748/failed-live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/missing-ebay-source-diagnostic-20260805-214748/relation-inventory.json` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `analytics.auction_alerts`, `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.completeness_premium`, `analytics.emotional_damage`, `analytics.midfication_detection`, `analytics.normalization_work_queue`, `analytics.obi_premium`, `analytics.obi_variant_price_summary`, `analytics.pressing_assignment_queue`, `raw.page`, `system.auction_ingestion_identity`, `system.auction_pressing_assignment_audit_event`, `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.completeness_cohort_summary`, `system.component_type`, `system.condition_grade`, `system.crawl_job`, `system.current_listing_completeness_alert`, `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.new_auction_assignment_queue`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `system.reference_audit_event`, `system.source`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_comparable_review`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_detail`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.auction_price_snapshot`, `warehouse.auction_purchase_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source`, `warehouse.listing_lineage`, `warehouse.listing_lineage_member`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/missing-ebay-source-diagnostic-20260805-225154/failed-live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/missing-ebay-source-diagnostic-20260805-225154/relation-inventory.json` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `analytics.auction_alerts`, `analytics.auction_collector_base`, `analytics.auction_scores`, `analytics.completeness_premium`, `analytics.emotional_damage`, `analytics.midfication_detection`, `analytics.normalization_work_queue`, `analytics.obi_premium`, `analytics.obi_variant_price_summary`, `analytics.pressing_assignment_queue`, `raw.page`, `system.auction_ingestion_identity`, `system.auction_pressing_assignment_audit_event`, `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.completeness_cohort_summary`, `system.component_type`, `system.condition_grade`, `system.crawl_job`, `system.current_listing_completeness_alert`, `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.new_auction_assignment_queue`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `system.reference_audit_event`, `system.source`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_comparable_review`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_detail`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.auction_price_snapshot`, `warehouse.auction_purchase_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source`, `warehouse.listing_lineage`, `warehouse.listing_lineage_member`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/mr2276-cohort-20260802-224931/curation-result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-empty-packet-sanitize-20260804-132054/packet-before-sanitize/README.md` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-empty-packet-sanitize-20260804-132054/packet-before-sanitize/current-cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-empty-packet-sanitize-20260804-132054/packet-before-sanitize/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-empty-packet-sanitize-20260804-132054/packet-before-sanitize/packet-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-empty-packet-sanitize-20260804-132054/safe-review/packet-review-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-observed-components-20260802-233201/result.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-packet-canonicalization-20260804-125540/canonical/mr2276-review-packet/README.md` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-packet-canonicalization-20260804-125540/canonical/mr2276-review-packet/current-cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-packet-canonicalization-20260804-125540/canonical/mr2276-review-packet/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-packet-canonicalization-20260804-125540/canonical/mr2276-review-packet/packet-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-packet-review-20260804-131237/packet-review-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-reviewed-packet-20260804-130921/README.md` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-reviewed-packet-20260804-130921/current-cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-reviewed-packet-20260804-130921/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/mr2276-reviewed-packet-20260804-130921/packet-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/new-auction-ingest-contract-20260804-234929/contract.json` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `raw.py`, `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.capture_media_profile_audit`, `system.capture_reference_audit`, `system.completeness_changed_fields`, `system.component_type`, `system.condition_grade`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_snapshot_id_seq`, `system.media_profile_audit_event`, `system.media_profile_component`, `system.py`, `system.reject_completeness_snapshot_mutation`, `system.reject_media_profile_audit_mutation`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_component_observation_id_seq`, `warehouse.auction_id_seq`, `warehouse.auction_pressing_assignment`, `warehouse.auction_pressing_assignment_id_seq`, `warehouse.pressing_component_expectation`, `warehouse.pressing_component_expectation_id_seq`, `warehouse.pressing_identity`, `warehouse.pressing_identity_id_seq`, `warehouse.py`, `warehouse.release_family`, `warehouse.release_family_id_seq` |
| `logs/new-auction-intake-20260805-000244/disposable-service-acceptance.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/new-auction-intake-20260805-000244/ingest-dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/new-auction-sidebar-navigation-20260805-143843/before-fix/accept_new_auction_intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/new-auction-sidebar-navigation-20260805-143843/before-fix/test_accept_new_auction_intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/new-auction-sidebar-navigation-20260805-143843/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/next-auction-refresh-plan-20260806-184914/recent-job-diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/next-auction-refresh-plan-20260806-184914/sanitized-source-config.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/next-crawl-entrypoint-audit-20260806-184309/entrypoints.json` | `MANUAL_REVIEW` | true | true | false | `raw.py`, `system.py`, `warehouse.py` |
| `logs/next-crawl-entrypoint-audit-20260806-184526/cohort-report.json` | `MANUAL_REVIEW` | false | false | false | `raw.page`, `system.crawl_job`, `warehouse.auction` |
| `logs/next-crawl-entrypoint-audit-20260806-184526/entrypoints.json` | `MANUAL_REVIEW` | true | true | false | `raw.py`, `system.py`, `warehouse.py` |
| `logs/next-curation-evidence-20260802-223102/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/next-fresh-ebay-ingestion-20260810-123939/ingest/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/next-reviewed-ingest-audit-20260806-132324/cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/next-reviewed-ingest-decision-20260806-174022/decision.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/next-reviewed-ingest-decision-20260806-183702/decision.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/848-selection.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/001-auction-before-colima-ebay-crawl-20260806-185844.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/002-auction-before-ebay-job-9-ingest-20260806-200504.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/003-auction-before-explicit-ebay-ingest-20260805-233858.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/004-auction-before-protected-count-ingest-20260805-234456.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/005-auction-before-reviewed-ingest-20260805-201831.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/006-auction-before-reviewed-ingest-20260805-201928.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/007-auction-before-reviewed-ingest-20260805-205912.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/008-auction-before-reviewed-ingest-20260805-210908.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/009-auction-before-reviewed-ingest-20260805-211721.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/010-auction-before-reviewed-ingest-20260805-212837.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/011-auction-warehouse-before-wizard.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/013-auction-warehouse-before-analytics.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/015-auction-warehouse.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/016-auction-warehouse-before-completeness-snapshots.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/017-auction-warehouse-before-completeness-snapshots.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/018-auction-warehouse-before-coverage-threshold.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/019-auction-warehouse-before-evidence-registry.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/021-auction-warehouse-before-sealed-exception.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/022-live-ingest-20260805-151928.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/023-auction-warehouse-before-mr2276.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/024-auction-warehouse-before-components.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/025-auction-warehouse-before-verdict-rules.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/026-auction-warehouse-before-workbench.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/027-auction_warehouse-20260725-121034.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/028-auction_warehouse-20260725-122136.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/029-auction_warehouse-20260725-164328.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/030-auction_warehouse-20260725-164332.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/031-auction_warehouse-20260725-180732.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/032-auction_warehouse-20260725-214747.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/033-auction_warehouse-20260726-150152.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/034-auction_warehouse-20260726-150155.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/035-auction_warehouse-20260726-152655.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/036-auction_warehouse-20260726-152656.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/037-auction_warehouse-20260726-152659.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/038-auction_warehouse-20260726-153535.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/039-auction_warehouse-20260726-170459.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/040-auction_warehouse-after-buyee-20260726-182718.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/041-auction_warehouse-after-buyee-detail-enrichment-20260731-104549.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/042-auction_warehouse-after-destructive-ebay-sync-20260727-123953.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/043-auction_warehouse-after-finalized-ebay-merge-20260727-130334.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/044-auction_warehouse-after-finalized-latest-reporting-20260730-164032.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/045-auction_warehouse-after-latest-reporting-20260730-161913.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/046-auction_warehouse-after-managed-collector-views-20260728-095201.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/047-auction_warehouse-after-pending-buyee-20260730-145825.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/048-auction_warehouse-after-review-view-toc-recovery-20260727-170926.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/049-auction_warehouse-after-safe-ebay-incremental-resume-20260727-125323.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/050-auction_warehouse-before-all-source-refresh-20260730-115054.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/051-auction_warehouse-before-all-source-refresh-20260730-141335.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/052-auction_warehouse-before-buyee-20260726-180626.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/053-auction_warehouse-before-buyee-apply-20260726-182718.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/054-auction_warehouse-before-buyee-detail-enrichment-20260731-101727.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/055-auction_warehouse-before-collector-rebuild-20260727-144630.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/056-auction_warehouse-before-collector-view-repair-20260727-155914.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/057-auction_warehouse-before-ebay-20260726-203538.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/058-auction_warehouse-before-ebay-authenticated-20260727-113835.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/059-auction_warehouse-before-ebay-cdp-20260726-230039.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/060-auction_warehouse-before-ebay-derived-backfill-20260727-144118.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/061-auction_warehouse-before-ebay-sync-repair-20260727-122424.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/062-auction_warehouse-before-final-collector-view-repair-20260727-161511.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/063-auction_warehouse-before-finalizing-ebay-merge-20260727-130332.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/064-auction_warehouse-before-latest-reporting-20260730-154805.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/065-auction_warehouse-before-latest-reporting-20260730-161848.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/066-auction_warehouse-before-live-ui-source-repair-20260731-100903.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/067-auction_warehouse-before-managed-collector-views-20260728-095124.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/068-auction_warehouse-before-pending-buyee-20260730-145813.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/069-auction_warehouse-before-reporting-audit-finalization-20260730-164008.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/070-auction_warehouse-before-review-view-toc-recovery-20260727-170917.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/071-auction_warehouse-before-safe-ebay-incremental-resume-20260727-125321.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/072-auction_warehouse-before-safe-sync-backfill-20260727-143533.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/073-auction_warehouse-viewtest-20260728_141333.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/074-auction_warehouse-viewtest-20260728_151340.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/075-auction_warehouse-viewtest-20260729_004321.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/076-auction_warehouse-viewtest-20260729_101505.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/079-auction_warehouse-after-buyee-live-20260725-010410.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/080-auction_warehouse-after-buyee-recrawl-20260725-005551.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/081-auction_warehouse-after-buyee-schema-fix-20260725-011110.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/082-auction_warehouse-after-clean-fx-rebuild-20260725-034833.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/083-auction_warehouse-after-local-price-fix-20260725-004812.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/084-auction_warehouse-before-ast-fx-fix-20260725-033810.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/085-auction_warehouse-before-buyee-live-20260725-010410.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/086-auction_warehouse-before-buyee-recrawl-20260725-005551.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/087-auction_warehouse-before-buyee-schema-fix-20260725-011110.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/088-auction_warehouse-before-clean-fx-rebuild-20260725-034833.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/089-auction_warehouse-before-derived-rebuild-20260725-003118.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/090-auction_warehouse-before-enhanced-review-20260725-020927.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/091-auction_warehouse-before-field-repair-20260725-003834.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/092-auction_warehouse-before-fx-finish-20260725-024327.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/093-auction_warehouse-before-fx-split-20260725-024747.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/094-auction_warehouse-before-local-price-fix-20260725-004756.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/095-auction_warehouse-before-reconstruction-20260725-002735.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/096-auction_warehouse-before-robust-fx-fix-20260725-033408.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/097-auction_warehouse-before-view-repair-20260725-023822.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/098-auction_warehouse-field-repaired-20260725-003851.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/099-auction_warehouse-restored-20260725-002325.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-848-to-850-20260807-163612/auction-data/100-auction-warehouse-before-reference-audit.dump.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-pre-job9-848-to-850-20260807-224259/auction-data.sql` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-pre-job9-848-to-850-20260807-225007/auction-data.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/prove-pre-job9-848-to-850-20260807-225934/auction-data.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/prove-pre-job9-848-to-850-20260807-234319/auction-data.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/prove-pre-job9-848-to-850-20260808-191532/auction-data.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/prove-pre-job9-848-to-850-20260808-193845/auction-data.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/prove-pre-job9-848-to-850-20260808-202447/added-provenance.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-pre-job9-848-to-850-20260808-202447/auction-data.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/prove-pre-job9-848-to-850-20260808-204009/added-provenance.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/prove-pre-job9-848-to-850-20260808-204009/auction-data.sql` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `logs/recent-export-browser-20260801-181958/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/recent-export-diagnosis-20260801-170254/recent-ingestion-latest-10.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/recent-export-diagnosis-20260801-170254/warehouse-auction-latest-10.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-201831/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-201928/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-205912/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-210908/dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-210908/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-211721/dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-211721/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-211721/live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-211721/live-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-212837/dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-212837/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-212837/live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-colima-ingest-20260805-212837/live-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ebay-job-9-ingest-20260806-200504/dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ebay-job-9-ingest-20260806-200504/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ebay-job-9-ingest-20260806-200504/live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ebay-job-9-ingest-20260806-200504/live-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-explicit-source-ingest-20260805-233858/dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-explicit-source-ingest-20260805-233858/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-explicit-source-ingest-20260805-233858/live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-explicit-source-ingest-20260805-233858/live-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ingest-child-env-fix-20260805-212831/dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ingest-child-env-fix-20260805-212831/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ingest-psycopg-url-fix-20260805-210905/wrapper-dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-ingest-psycopg-url-fix-20260805-210905/wrapper-dry-run.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-protected-count-ingest-20260805-234456/dry-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-protected-count-ingest-20260805-234456/dry-run-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-protected-count-ingest-20260805-234456/live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-protected-count-ingest-20260805-234456/live-run/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/reviewed-protected-count-ingest-20260805-234456/success.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/safe-sync-repair/continuation-20260727-144115/backfill.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector` |
| `logs/schema-audit/20260727-133328/schema-audit.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `raw.page`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source` |
| `logs/schema-audit/continuation-20260727-142310/schema-audit-continuation.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `raw.page`, `system.crawl_job`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_detail`, `warehouse.auction_purchase_review`, `warehouse.gripsweat_sale`, `warehouse.gripsweat_source` |
| `logs/sealed-completeness-contract-v2-20260803-001355/auction-collector-base-view.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `system.condition_grade`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_completeness`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_event_context`, `warehouse.auction_pressing_assignment`, `warehouse.listing_lineage_member`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/sealed-completeness-contract-v2-20260803-001355/auction-completeness-view.sql` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity` |
| `logs/second-reviewed-ingest-diagnostic-20260805-214120/live-ingest-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/selection-redesign/browser-20260731-165818/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/selection-redesign/browser-semantic-20260731-173818/failure/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/selection-redesign/browser-semantic-20260731-174848/failure/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/stage3-legacy-schema-fix-20260804-125913/pending-before-fix/review_and_apply_pressing_packet.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.component_type`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/stage3-legacy-schema-fix-20260804-125913/pending-before-fix/test_review_and_apply_pressing_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/stale-auction-postgres-quarantine-20260805-200523/auction-etl-db-1-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/stale-auction-postgres-quarantine-20260805-200523/auction-postgres-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/stale-auction-postgres-quarantine-20260805-200523/before-change/audit_auction_docker_contexts.py` | `MANUAL_REVIEW` | false | true | false | `warehouse.auction` |
| `logs/state-safe-media-profiles-20260804-174018/source-before-install/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/state-safe-media-profiles-20260804-174018/source-before-install/media_aware_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/state-safe-media-profiles-20260804-174402/source-before-install/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/state-safe-media-profiles-20260804-174402/source-before-install/media_aware_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `system.evidence_source_registry`, `system.media_profile_component`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/state-safe-media-profiles-20260804-180433/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/state-safe-media-profiles-20260804-180433/source-before-install/collector_analytics_editor.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/state-safe-media-profiles-20260804-180433/source-before-install/media_aware_reference.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.component_type`, `system.evidence_source_registry`, `system.media_profile_component`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_component_observation`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/state-safe-resource-classification-20260804-181959/before-fix/accept_state_safe_completeness_and_profiles.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/state-safe-resource-classification-20260804-181959/before-fix/test_state_safe_completeness_and_media_profile_acceptance.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/state-safe-resource-classification-20260804-181959/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/state-safe-sidebar-navigation-20260804-182358/before-fix/accept_state_safe_completeness_and_profiles.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/state-safe-sidebar-navigation-20260804-182358/before-fix/test_state_safe_completeness_and_media_profile_acceptance.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/state-safe-sidebar-navigation-20260804-182358/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/streamlit-width-cleanup/20260731-152713/browser/success/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/streamlit-width-cleanup/20260731-152713/browser-acceptance.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-human-acceptance/20260730-182806/acceptance-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-live-acceptance/20260730-171504/acceptance-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/ui-live-acceptance/post-enrichment-20260731-104549/diagnostics/final-failure/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-live-acceptance/telemetry-schema-20260731-150326/streamlit_dataframe_schema.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-live-acceptance/total-matches-20260731-145346/browser/failure/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-live-acceptance/venv-recovery-20260731-111638/diagnostics/acceptance-failure/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-live-acceptance/venv-recovery-20260731-111638/diagnostics/marketplace-timeout/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-live-acceptance/venv-recovery-20260731-140216/diagnostics/acceptance-failure/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/ui-live-acceptance/venv-recovery-20260731-140216/diagnostics/marketplace-timeout/diagnostics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/wizard-acceptance-resume-20260803-235832/pending-before-fix/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-acceptance-resume-20260803-235832/pending-before-fix/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/wizard-acceptance-resume-20260803-235832/pending-before-fix/test_accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-acceptance-resume-20260803-235832/pending-before-fix/test_export_pressing_curation_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-acceptance-resume-20260804-000330/pending-before-fix/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-acceptance-resume-20260804-000330/pending-before-fix/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/wizard-acceptance-resume-20260804-000330/pending-before-fix/test_accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-acceptance-resume-20260804-000330/pending-before-fix/test_export_pressing_curation_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-default-cohort-resume-20260804-083535/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/wizard-default-cohort-resume-20260804-083535/pending-before-fix/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-default-cohort-resume-20260804-083535/pending-before-fix/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/wizard-default-cohort-resume-20260804-083535/pending-before-fix/test_accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-default-cohort-resume-20260804-083535/pending-before-fix/test_export_pressing_curation_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-evidence-handoff-20260804-134246/files-before-install/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/wizard-evidence-handoff-20260804-134246/files-before-install/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/wizard-evidence-handoff-20260804-134246/files-before-install/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/wizard-evidence-handoff-20260804-134533/files-before-install/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/wizard-evidence-handoff-20260804-134533/files-before-install/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/wizard-evidence-handoff-20260804-134533/files-before-install/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/wizard-evidence-handoff-20260804-150244/files-before-install/8_Cohort_Curation_Wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/wizard-evidence-handoff-20260804-150244/files-before-install/9_Evidence_Intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `logs/wizard-evidence-handoff-20260804-150244/files-before-install/evidence_intake.py` | `MANUAL_REVIEW` | false | true | false | `system.component_type`, `system.evidence_source_registry` |
| `logs/wizard-health-resume-20260804-111555/browser/report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/wizard-health-resume-20260804-111555/mr2276-review-packet/README.md` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/wizard-health-resume-20260804-111555/mr2276-review-packet/current-cohort-report.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/wizard-health-resume-20260804-111555/mr2276-review-packet/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/wizard-health-resume-20260804-111555/mr2276-review-packet/packet-summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `logs/wizard-navigation-resume-20260804-082835/pending-before-navigation-fix/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-navigation-resume-20260804-082835/pending-before-navigation-fix/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/wizard-navigation-resume-20260804-082835/pending-before-navigation-fix/test_accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-navigation-resume-20260804-082835/pending-before-navigation-fix/test_export_pressing_curation_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-classification-20260804-085701/pending-before-resource-fix/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-classification-20260804-085701/pending-before-resource-fix/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/wizard-resource-classification-20260804-085701/pending-before-resource-fix/test_accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-classification-20260804-085701/pending-before-resource-fix/test_export_pressing_curation_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-classification-20260804-102800/pending-before-resource-fix/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-classification-20260804-102800/pending-before-resource-fix/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/wizard-resource-classification-20260804-102800/pending-before-resource-fix/test_accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-classification-20260804-102800/pending-before-resource-fix/test_export_pressing_curation_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-direct-20260804-110330/pending-before-direct-fix/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-direct-20260804-110330/pending-before-direct-fix/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `logs/wizard-resource-direct-20260804-110330/pending-before-direct-fix/test_accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `logs/wizard-resource-direct-20260804-110330/pending-before-direct-fix/test_export_pressing_curation_packet.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/anonymous/component_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/anonymous/extensions_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/ActorSafetyLists/9.5220.3721/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/ActorSafetyLists/9.5220.3721/listdata.json` | `MANUAL_REVIEW` | false | true | false | `account.accurate`, `account.activix`, `account.adobe`, `account.airtrip`, `account.alberta`, `account.alibabacloud`, `account.aliyun`, `account.amazon`, `account.amway`, `account.app`, `account.appfolio`, `account.apple`, `account.apps`, `account.asr`, `account.astrum`, `account.asus`, `account.autenti`, `account.authorize`, `account.avg`, `account.bannerhealth`, `account.battle`, `account.bbc`, `account.beacons`, `account.bellmedia`, `account.blackbaud`, `account.bliblitiket`, `account.booking`, `account.box`, `account.brivo`, `account.buffer`, `account.cccmypath`, `account.cebupacificair`, `account.cengage`, `account.chrobinson`, `account.chungdahm`, `account.cirrusaircraft`, `account.cloudresearch`, `account.coindcx`, `account.collegeboard`, `account.commonspirit`, `account.constellation`, `account.coop`, `account.covermymeds`, `account.documentolog`, `account.docusign`, `account.easyparcel`, `account.elama`, `account.emburse`, `account.envato`, `account.f5`, `account.fido`, `account.formula1`, `account.garena`, `account.godaddy`, `account.goguardian`, `account.gpos`, `account.grammarly`, `account.hmrc`, `account.hotmart`, `account.hp`, `account.hrblock`, `account.idm`, `account.ielts`, `account.indeed`, `account.individuals`, `account.innovamd`, `account.inspirafinancial`, `account.irfarabi`, `account.johnlewis`, `account.kdocs`, `account.lenovo`, `account.lguplus`, `account.libertymutual`, `account.line`, `account.live`, `account.luminpdf`, `account.mail`, `account.massimodutti`, `account.maxar`, `account.mayoclinic`, `account.mekari`, `account.microsoft`, `account.miles`, `account.mindplay`, `account.minimaxi`, `account.momentum`, `account.mongodb`, `account.mygovid`, `account.myiuhealth`, `account.mylakeviewloan`, `account.myparcel`, `account.ncbi`, `account.nexiuslearning`, `account.ninjatrader`, `account.noon`, `account.nzpost`, `account.okioki`, `account.one`, `account.optumbank`, `account.pancake`, `account.pandaexpress`, `account.pazarama`, `account.plenti`, `account.proton`, `account.publix`, `account.qualcomm`, `account.rakuten`, `account.rallit`, `account.relianceretail`, `account.ring`, `account.rogers`, `account.rogersmembercentre`, `account.rushmoreservicing`, `account.sainsburys`, `account.samsung`, `account.shop`, `account.signaturit`, `account.siigo`, `account.simplepractice`, `account.sitegiant`, `account.snappet`, `account.sobrus`, `account.sony`, `account.spitfireaudio`, `account.spx`, `account.squarespace`, `account.stradivarius`, `account.student`, `account.students`, `account.t`, `account.tamin`, `account.teamviewer`, `account.tendata`, `account.texashealth`, `account.tfl`, `account.thaibulksms`, `account.thehartford`, `account.toyota`, `account.uber`, `account.ui`, `account.uipath`, `account.ulys`, `account.unext`, `account.vcccd`, `account.venmo`, `account.vkplay`, `account.voicemod`, `account.wal`, `account.web`, `account.weverse`, `account.workers`, `account.wps`, `account.xiaomi`, `account.zara`, `account.zarahome`, `analytics.appspot`, `analytics.bestofluck`, `analytics.fatmedia`, `identity.accessacloud`, `identity.account`, `identity.ade`, `identity.adp`, `identity.airfranceklm`, `identity.airnewzealand`, `identity.alveno`, `identity.appen`, `identity.athenahealth`, `identity.att`, `identity.axxessweb`, `identity.brinksinc`, `identity.britishcouncil`, `identity.checkout`, `identity.checkr`, `identity.corpayone`, `identity.dataspace`, `identity.deliveroo`, `identity.deltadental`, `identity.denison`, `identity.dentalpro`, `identity.designmynight`, `identity.directv`, `identity.doordash`, `identity.elluciancloud`, `identity.enterprise`, `identity.ep`, `identity.eset`, `identity.flickr`, `identity.gb`, `identity.getpostman`, `identity.gov`, `identity.gympass`, `identity.hapag`, `identity.healthsafe`, `identity.homeoffice`, `identity.ibs`, `identity.iris`, `identity.joyclub`, `identity.ksavisa`, `identity.leadsquared`, `identity.lokos`, `identity.maine`, `identity.meindaad`, `identity.myisolved`, `identity.myvas`, `identity.myworkday`, `identity.nationwide`, `identity.noordhoff`, `identity.o2`, `identity.onehealthcareid`, `identity.onxmaps`, `identity.openeasy`, `identity.oraclecloud`, `identity.pbisapps`, `identity.pennymac`, `identity.peoplespartnership`, `identity.platform`, `identity.prd`, `identity.prismhr`, `identity.santillanaconnect`, `identity.seller`, `identity.staples`, `identity.symfonia`, `identity.team`, `identity.teamsystem`, `identity.tele2`, `identity.telkomsel`, `identity.thoughtspotlogin`, `identity.tmtickets`, `identity.trinet`, `identity.tvs`, `identity.ucsb`, `identity.vanguard`, `identity.vaxcare`, `identity.verisk`, `identity.virginatlantic`, `identity.vismaonline`, `identity.walmart`, `identity.wd10`, `identity.wd102`, `identity.wd103`, `identity.wd108`, `identity.wd12`, `identity.wd501`, `identity.wd502`, `identity.wd503`, `identity.wellsoneexpensemanager`, `identity.wowway`, `identity.zelispayments`, `identity.zillow`, `ops.gr`, `ops.prismm`, `ops.zomans`, `system.co`, `system.com`, `system.coop`, `system.netsuite`, `system.port`, `warehouse.getir` |
| `profiles/buyee/ActorSafetyLists/9.5220.3721/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/AmountExtractionHeuristicRegexes/4/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/AmountExtractionHeuristicRegexes/4/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/CaptchaProviders/8.5419.4434/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/CaptchaProviders/8.5419.4434/captcha_providers.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/CaptchaProviders/8.5419.4434/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/CertificateRevocation/10719/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/CertificateRevocation/10719/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/Crowd Deny/2026.8.13.60/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/Crowd Deny/2026.8.13.60/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/FileTypePolicies/145.0.7584.0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/FileTypePolicies/145.0.7584.0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/FirstPartySetsPreloaded/2025.7.24.0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/FirstPartySetsPreloaded/2025.7.24.0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/FirstPartySetsPreloaded/2025.7.24.0/sets.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/buyee/MEIPreload/1.1.0.3/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/MEIPreload/1.1.0.3/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/OnDeviceHeadSuggestModel/20251024.824731831.14/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/OnDeviceHeadSuggestModel/20251024.824731831.14/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/OptimizationHints/727/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/OptimizationHints/727/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/PKIMetadata/1748/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/PKIMetadata/1748/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/SSLErrorAssistant/7/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/SSLErrorAssistant/7/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/SafetyTips/3091/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/SafetyTips/3091/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/Subresource Filter/Unindexed Rules/9.70.0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/Subresource Filter/Unindexed Rules/9.70.0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/TrustTokenKeyCommitments/2026.8.3.1/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/TrustTokenKeyCommitments/2026.8.3.1/keys.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/buyee/TrustTokenKeyCommitments/2026.8.3.1/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/WasmTtsEngine/20260806.1/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/WasmTtsEngine/20260806.1/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/WasmTtsEngine/20260806.1/voices.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/WasmTtsEngine/20260806.1/wasm_tts_manifest_v3.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/ZxcvbnData/3/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/ZxcvbnData/3/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/component_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/buyee/extensions_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/ActorSafetyLists/9.5220.3721/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/ActorSafetyLists/9.5220.3721/listdata.json` | `MANUAL_REVIEW` | false | true | false | `account.accurate`, `account.activix`, `account.adobe`, `account.airtrip`, `account.alberta`, `account.alibabacloud`, `account.aliyun`, `account.amazon`, `account.amway`, `account.app`, `account.appfolio`, `account.apple`, `account.apps`, `account.asr`, `account.astrum`, `account.asus`, `account.autenti`, `account.authorize`, `account.avg`, `account.bannerhealth`, `account.battle`, `account.bbc`, `account.beacons`, `account.bellmedia`, `account.blackbaud`, `account.bliblitiket`, `account.booking`, `account.box`, `account.brivo`, `account.buffer`, `account.cccmypath`, `account.cebupacificair`, `account.cengage`, `account.chrobinson`, `account.chungdahm`, `account.cirrusaircraft`, `account.cloudresearch`, `account.coindcx`, `account.collegeboard`, `account.commonspirit`, `account.constellation`, `account.coop`, `account.covermymeds`, `account.documentolog`, `account.docusign`, `account.easyparcel`, `account.elama`, `account.emburse`, `account.envato`, `account.f5`, `account.fido`, `account.formula1`, `account.garena`, `account.godaddy`, `account.goguardian`, `account.gpos`, `account.grammarly`, `account.hmrc`, `account.hotmart`, `account.hp`, `account.hrblock`, `account.idm`, `account.ielts`, `account.indeed`, `account.individuals`, `account.innovamd`, `account.inspirafinancial`, `account.irfarabi`, `account.johnlewis`, `account.kdocs`, `account.lenovo`, `account.lguplus`, `account.libertymutual`, `account.line`, `account.live`, `account.luminpdf`, `account.mail`, `account.massimodutti`, `account.maxar`, `account.mayoclinic`, `account.mekari`, `account.microsoft`, `account.miles`, `account.mindplay`, `account.minimaxi`, `account.momentum`, `account.mongodb`, `account.mygovid`, `account.myiuhealth`, `account.mylakeviewloan`, `account.myparcel`, `account.ncbi`, `account.nexiuslearning`, `account.ninjatrader`, `account.noon`, `account.nzpost`, `account.okioki`, `account.one`, `account.optumbank`, `account.pancake`, `account.pandaexpress`, `account.pazarama`, `account.plenti`, `account.proton`, `account.publix`, `account.qualcomm`, `account.rakuten`, `account.rallit`, `account.relianceretail`, `account.ring`, `account.rogers`, `account.rogersmembercentre`, `account.rushmoreservicing`, `account.sainsburys`, `account.samsung`, `account.shop`, `account.signaturit`, `account.siigo`, `account.simplepractice`, `account.sitegiant`, `account.snappet`, `account.sobrus`, `account.sony`, `account.spitfireaudio`, `account.spx`, `account.squarespace`, `account.stradivarius`, `account.student`, `account.students`, `account.t`, `account.tamin`, `account.teamviewer`, `account.tendata`, `account.texashealth`, `account.tfl`, `account.thaibulksms`, `account.thehartford`, `account.toyota`, `account.uber`, `account.ui`, `account.uipath`, `account.ulys`, `account.unext`, `account.vcccd`, `account.venmo`, `account.vkplay`, `account.voicemod`, `account.wal`, `account.web`, `account.weverse`, `account.workers`, `account.wps`, `account.xiaomi`, `account.zara`, `account.zarahome`, `analytics.appspot`, `analytics.bestofluck`, `analytics.fatmedia`, `identity.accessacloud`, `identity.account`, `identity.ade`, `identity.adp`, `identity.airfranceklm`, `identity.airnewzealand`, `identity.alveno`, `identity.appen`, `identity.athenahealth`, `identity.att`, `identity.axxessweb`, `identity.brinksinc`, `identity.britishcouncil`, `identity.checkout`, `identity.checkr`, `identity.corpayone`, `identity.dataspace`, `identity.deliveroo`, `identity.deltadental`, `identity.denison`, `identity.dentalpro`, `identity.designmynight`, `identity.directv`, `identity.doordash`, `identity.elluciancloud`, `identity.enterprise`, `identity.ep`, `identity.eset`, `identity.flickr`, `identity.gb`, `identity.getpostman`, `identity.gov`, `identity.gympass`, `identity.hapag`, `identity.healthsafe`, `identity.homeoffice`, `identity.ibs`, `identity.iris`, `identity.joyclub`, `identity.ksavisa`, `identity.leadsquared`, `identity.lokos`, `identity.maine`, `identity.meindaad`, `identity.myisolved`, `identity.myvas`, `identity.myworkday`, `identity.nationwide`, `identity.noordhoff`, `identity.o2`, `identity.onehealthcareid`, `identity.onxmaps`, `identity.openeasy`, `identity.oraclecloud`, `identity.pbisapps`, `identity.pennymac`, `identity.peoplespartnership`, `identity.platform`, `identity.prd`, `identity.prismhr`, `identity.santillanaconnect`, `identity.seller`, `identity.staples`, `identity.symfonia`, `identity.team`, `identity.teamsystem`, `identity.tele2`, `identity.telkomsel`, `identity.thoughtspotlogin`, `identity.tmtickets`, `identity.trinet`, `identity.tvs`, `identity.ucsb`, `identity.vanguard`, `identity.vaxcare`, `identity.verisk`, `identity.virginatlantic`, `identity.vismaonline`, `identity.walmart`, `identity.wd10`, `identity.wd102`, `identity.wd103`, `identity.wd108`, `identity.wd12`, `identity.wd501`, `identity.wd502`, `identity.wd503`, `identity.wellsoneexpensemanager`, `identity.wowway`, `identity.zelispayments`, `identity.zillow`, `ops.gr`, `ops.prismm`, `ops.zomans`, `system.co`, `system.com`, `system.coop`, `system.netsuite`, `system.port`, `warehouse.getir` |
| `profiles/chrome-cdp-facerecords/ActorSafetyLists/9.5220.3721/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/AmountExtractionHeuristicRegexes/4/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/AmountExtractionHeuristicRegexes/4/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CaptchaProviders/8.5419.4434/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CaptchaProviders/8.5419.4434/captcha_providers.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CaptchaProviders/8.5419.4434/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CertificateRevocation/10668/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CertificateRevocation/10668/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CertificateRevocation/10675/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CertificateRevocation/10675/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CommerceHeuristics/2023.3.30.1305/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/CommerceHeuristics/2023.3.30.1305/commerce_global_heuristics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/CommerceHeuristics/2023.3.30.1305/commerce_hint_heuristics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/CommerceHeuristics/2023.3.30.1305/commerce_product_id_heuristics.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/CommerceHeuristics/2023.3.30.1305/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Crowd Deny/2026.7.23.61/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Crowd Deny/2026.7.23.61/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/cs/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/da/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/de/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/el/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/en/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/es/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/es_419/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/fi/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/fr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/fr_CA/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/hr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/hu/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/it/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/ja/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/ko/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/nb/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/nl/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/pl/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/pt_BR/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/pt_PT/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/ru/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/sk/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/sr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/sv/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/tr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/zh_CN/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_locales/zh_TW/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/dnr_rules/sdk_block_rules.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/json/engines.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/fheoggkfdfchfphceeifdbepaooicaho/8.1.0.9615_0/manifest.json` | `MANUAL_REVIEW` | false | false | false | `analytics.apis`, `analytics.qa` |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/bg/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ca/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/cs/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/da/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/de/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/el/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/en/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/en_GB/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/es/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/es_419/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/et/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/fi/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/fil/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/fr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/hi/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/hr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/hu/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/id/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/it/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ja/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ko/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/lt/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/lv/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/nb/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/nl/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/pl/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/pt_BR/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/pt_PT/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ro/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ru/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sk/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sl/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sv/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/th/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/tr/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/uk/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/vi/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/zh_CN/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/zh_TW/messages.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_metadata/computed_hashes.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/FileTypePolicies/145.0.7584.0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/FileTypePolicies/145.0.7584.0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/FirstPartySetsPreloaded/2025.7.24.0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/FirstPartySetsPreloaded/2025.7.24.0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/FirstPartySetsPreloaded/2025.7.24.0/sets.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/HistorySearch/6.7431.9692/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/HistorySearch/6.7431.9692/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/MEIPreload/1.1.0.3/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/MEIPreload/1.1.0.3/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/OnDeviceHeadSuggestModel/20251024.824731831.14/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/OnDeviceHeadSuggestModel/20251024.824731831.14/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/OptimizationHints/714/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/OptimizationHints/714/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/OptimizationHints/715/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/OptimizationHints/715/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/PKIMetadata/1723/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/PKIMetadata/1723/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/PKIMetadata/1728/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/PKIMetadata/1728/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/SSLErrorAssistant/7/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/SSLErrorAssistant/7/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/SafetyTips/3091/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/SafetyTips/3091/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Subresource Filter/Unindexed Rules/9.69.0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Subresource Filter/Unindexed Rules/9.69.0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Subresource Filter/Unindexed Rules/9.70.0/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/Subresource Filter/Unindexed Rules/9.70.0/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/TrustTokenKeyCommitments/2026.3.23.1/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/TrustTokenKeyCommitments/2026.3.23.1/keys.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `profiles/chrome-cdp-facerecords/TrustTokenKeyCommitments/2026.3.23.1/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260709.1/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260709.1/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260709.1/voices.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260709.1/wasm_tts_manifest_v3.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260723.1/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260723.1/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260723.1/voices.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/WasmTtsEngine/20260723.1/wasm_tts_manifest_v3.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/ZxcvbnData/3/_metadata/verified_contents.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/ZxcvbnData/3/manifest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/component_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/chrome-cdp-facerecords/extensions_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/facerecords/component_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/facerecords/extensions_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/gripsweat/component_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/gripsweat/extensions_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/gripsweat-audit/component_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/gripsweat-audit/extensions_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/gripsweat-probe/component_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `profiles/gripsweat-probe/extensions_crx_cache/metadata.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `pyproject.toml` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `railway.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/buyee-detail-enrichment/20260731-101727/coverage.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/dict-row-fix-20260730-144916/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/final-validation-20260730-164007/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/latest.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/ui-20260730-211513/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/ui-20260810-164629/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/ui-20260811-000338-74878/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/ui-20260811-153007-95979/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/validated-20260730-154805/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `reports/recent-ingestion/validated-20260730-161847/summary.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `scripts/accept_cohort_wizard.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/accept_collector_hover_click.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/accept_completeness_history.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/accept_evidence_intake_handoff.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/accept_media_aware_reference.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `scripts/accept_new_auction_intake.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/accept_state_safe_completeness_and_profiles.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/audit_auction_docker_contexts.py` | `MANUAL_REVIEW` | false | true | false | `warehouse.auction` |
| `scripts/audit_collector_db.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `scripts/audit_gripsweat_pagination.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/backfill_buyee_displayed_usd.py` | `MANUAL_REVIEW` | true | false | false | `system.auction_ingestion_identity`, `warehouse.auction` |
| `scripts/bootstrap_ebay_profile.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `scripts/collector_features.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_detail` |
| `scripts/crawl_buyee_live_details.py` | `MANUAL_REVIEW` | false | true | false | `system.auction_ingestion_identity`, `warehouse.auction`, `warehouse.auction_detail` |
| `scripts/crawl_ebay_chrome_cdp.py` | `MANUAL_REVIEW` | false | true | false | `raw.id` |
| `scripts/crawl_ebay_sources.py` | `MANUAL_REVIEW` | false | true | false | `raw.id`, `warehouse.auction` |
| `scripts/curate_collector_evidence.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `scripts/enrich_buyee_details.py` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction`, `warehouse.auction_detail` |
| `scripts/enrich_gripsweat_details.py` | `MANUAL_REVIEW` | false | true | false | `raw.strip`, `warehouse.gripsweat_sale` |
| `scripts/ensure_buyee_cdp_browser.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/ensure_buyee_owner.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `scripts/export_pressing_curation_packet.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.pressing_identity`, `warehouse.release_family` |
| `scripts/fix_collector_review_null_state.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/hard_test_ingestion_round_ui.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `raw.page`, `system.crawl_job`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment` |
| `scripts/hard_test_latest_refresh_ui.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `scripts/import_gripsweat_pagination_audit.py` | `MANUAL_REVIEW` | false | true | false | `warehouse.gripsweat_sale`, `warehouse.gripsweat_source` |
| `scripts/import_gripsweat_probe.py` | `MANUAL_REVIEW` | false | true | false | `warehouse.gripsweat_sale`, `warehouse.gripsweat_source` |
| `scripts/inspect_recent_ingestion.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | true | false | — |
| `scripts/install_collector_views.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `scripts/launch_latest_refresh_job.py` | `NO_DATABASE_SCOPE_SIGNAL` | true | false | false | — |
| `scripts/normalize_gripsweat_sales.py` | `MANUAL_REVIEW` | true | false | false | `warehouse.auction`, `warehouse.gripsweat_sale` |
| `scripts/normalize_gripsweat_source_schema.py` | `MANUAL_REVIEW` | true | false | false | `warehouse.gripsweat_source` |
| `scripts/phase_d_owner_backfill.py` | `ACCOUNT_AWARE` | true | true | true | `account.artist_marketplace`, `account.auction_listing`, `account.tracked_artist`, `identity.account`, `identity.account_member`, `identity.app_user`, `ops.refresh_job`, `system.auction_pressing_assignment_audit_event`, `system.current_listing_completeness_alert`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.auction_pressing_assignment` |
| `scripts/phase_d_owner_backfill_rollback.py` | `ACCOUNT_AWARE` | true | false | true | `account.auction_listing`, `account.tracked_artist`, `identity.account`, `identity.account_member`, `identity.app_user`, `ops.refresh_job` |
| `scripts/phase_d_scope_gate.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `scripts/probe_buyee_details.py` | `MANUAL_REVIEW` | false | false | false | `warehouse.auction` |
| `scripts/probe_gripsweat.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `scripts/reclassify_collector.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `warehouse.auction`, `warehouse.auction_collector` |
| `scripts/recover_auction_warehouse.py` | `MANUAL_REVIEW` | true | false | false | `warehouse.auction` |
| `scripts/repair_recovered_auction_fields.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_detail` |
| `scripts/review_and_apply_pressing_packet.py` | `ACCOUNT_SCOPE_REQUIRED` | false | true | false | `system.evidence_attachment`, `system.evidence_source_registry`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.reference_audit_event`, `warehouse.auction`, `warehouse.auction_analysis_input`, `warehouse.auction_behavior_observation`, `warehouse.auction_component_observation`, `warehouse.auction_condition_normalization`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_component_expectation`, `warehouse.pressing_identity`, `warehouse.release_family` |
| `scripts/run_buyee_owner.py` | `MANUAL_REVIEW` | true | true | false | `raw.decode` |
| `scripts/run_buyee_owner_job.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |
| `scripts/run_cloud_refresh_worker.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | — |
| `scripts/run_fresh_ebay_ingestion_round.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `identity.listing_id`, `identity.marketplace`, `raw.page`, `system.crawl_job`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment` |
| `scripts/run_ingest_with_assignment_queue.py` | `ACCOUNT_SCOPE_REQUIRED` | false | false | false | `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment` |
| `scripts/run_latest_auction_refresh.py` | `ACCOUNT_SCOPE_REQUIRED` | true | true | false | `warehouse.auction`, `warehouse.auction_collector`, `warehouse.auction_collector_effective`, `warehouse.auction_collector_review`, `warehouse.gripsweat_sale` |
| `scripts/run_multisource_ingestion_round.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `identity.listing_id`, `identity.marketplace`, `raw.page`, `system.crawl_job`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `system.new_auction_assignment_queue`, `warehouse.auction`, `warehouse.auction_pressing_assignment`, `warehouse.gripsweat_sale`, `warehouse.pressing_identity`, `warehouse.pressing_matrix_runout`, `warehouse.pressing_reference_catalog`, `warehouse.release_family` |
| `scripts/setup_collector_review_v2.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `warehouse.auction_collector` |
| `scripts/setup_gripsweat_schema.py` | `MANUAL_REVIEW` | false | false | false | `warehouse.gripsweat_sale`, `warehouse.gripsweat_source` |
| `scripts/setup_pressing_reference_catalog.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `warehouse.auction`, `warehouse.auction_pressing_assignment`, `warehouse.pressing_identity`, `warehouse.pressing_matrix_runout`, `warehouse.pressing_reference_catalog`, `warehouse.release_family` |
| `scripts/sync_warehouse_incremental.py` | `MANUAL_REVIEW` | true | true | false | `warehouse.auction` |
| `scripts/update_auction_fx.py` | `MANUAL_REVIEW` | true | false | false | `warehouse.auction` |
| `scripts/update_ingestion_audit.py` | `MANUAL_REVIEW` | true | false | false | `system.auction_ingestion_identity` |
| `scripts/upgrade_collector_review_schema.py` | `ACCOUNT_SCOPE_REQUIRED` | true | false | false | `warehouse.auction`, `warehouse.auction_collector` |
| `scripts/verify_buyee_session.py` | `NO_DATABASE_SCOPE_SIGNAL` | false | true | false | — |
| `tests/__init__.py` | `TEST` | false | false | false | — |
| `tests/integration/__init__.py` | `TEST` | false | false | false | — |
| `tests/integration/browser/__init__.py` | `TEST` | false | false | false | — |
| `tests/test_accept_cohort_wizard.py` | `TEST` | false | true | false | — |
| `tests/test_accept_completeness_history.py` | `TEST` | false | true | false | — |
| `tests/test_accept_evidence_intake_handoff.py` | `TEST` | false | true | false | — |
| `tests/test_accept_media_aware_reference.py` | `TEST` | false | true | false | — |
| `tests/test_accept_new_auction_intake.py` | `TEST` | false | true | false | — |
| `tests/test_app_navigation.py` | `TEST` | false | true | false | — |
| `tests/test_artist_refresh_status.py` | `TEST` | false | false | false | — |
| `tests/test_artist_tracking.py` | `TEST` | false | false | false | — |
| `tests/test_artist_tracking_refresh_wiring.py` | `TEST` | false | true | false | — |
| `tests/test_auction_ingest_job_smoke.py` | `TEST` | false | true | false | — |
| `tests/test_auction_ingest_worker_startup.py` | `TEST` | false | true | false | — |
| `tests/test_auction_intake.py` | `TEST` | false | true | false | — |
| `tests/test_buyee_background_cdp.py` | `TEST` | false | true | false | — |
| `tests/test_buyee_latest_refresh_new_only_details.py` | `TEST` | false | true | false | — |
| `tests/test_buyee_owner.py` | `TEST` | true | false | false | — |
| `tests/test_buyee_owner_liveness.py` | `TEST` | false | true | false | — |
| `tests/test_cloud_control_plane.py` | `TEST` | false | true | false | — |
| `tests/test_cloud_refresh_worker.py` | `TEST` | false | false | false | — |
| `tests/test_cohort_curation_wizard.py` | `TEST` | false | false | false | — |
| `tests/test_cohort_curation_wizard_page.py` | `TEST` | false | true | false | — |
| `tests/test_collector_analytics_editor.py` | `TEST` | false | true | false | — |
| `tests/test_collector_curation.py` | `TEST` | false | true | false | — |
| `tests/test_collector_curation_generated_columns.py` | `TEST` | false | true | false | — |
| `tests/test_collector_evidence.py` | `TEST` | false | true | false | — |
| `tests/test_collector_evidence_normalization_guard.py` | `TEST` | false | false | false | — |
| `tests/test_collector_export_ui.py` | `TEST` | false | false | false | — |
| `tests/test_collector_hover_click_acceptance_source.py` | `TEST` | false | false | false | — |
| `tests/test_collector_hover_click_grid.py` | `TEST` | false | true | false | — |
| `tests/test_collector_observation_bulk.py` | `TEST` | false | true | false | `system.evidence_source_registry` |
| `tests/test_collector_save_upsert.py` | `TEST` | false | true | false | `warehouse.auction_collector` |
| `tests/test_collector_views.py` | `TEST` | true | true | false | `warehouse.auction_collector_effective`, `warehouse.auction_collector_review` |
| `tests/test_completeness_history.py` | `TEST` | false | true | false | `system.listing_completeness_snapshot`, `warehouse.release_family` |
| `tests/test_completeness_history_migration.py` | `TEST` | false | false | false | `system.capture_automatic_completeness_snapshot`, `system.capture_listing_completeness_snapshot`, `system.listing_completeness_payload`, `system.listing_completeness_snapshot`, `system.listing_completeness_timeline`, `warehouse.auction_pressing_assignment` |
| `tests/test_completeness_history_page.py` | `TEST` | false | true | false | — |
| `tests/test_completeness_reference.py` | `TEST` | false | true | false | — |
| `tests/test_completeness_reference_page.py` | `TEST` | false | true | false | — |
| `tests/test_deployment_architecture_docs.py` | `TEST` | true | false | false | `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace` |
| `tests/test_deterministic_verdicts.py` | `TEST` | false | false | false | `system.deterministic_verdict_rule` |
| `tests/test_duplicate_dataframe_columns.py` | `TEST` | false | false | false | — |
| `tests/test_ebay_gripsweat_incremental_latest_refresh.py` | `TEST` | false | true | false | — |
| `tests/test_emotional_damage_coverage_migration.py` | `TEST` | false | true | false | `analytics.emotional_damage` |
| `tests/test_ensure_buyee_owner_recovery.py` | `TEST` | false | true | false | — |
| `tests/test_evidence_bulk_observation_page.py` | `TEST` | false | true | false | — |
| `tests/test_evidence_intake.py` | `TEST` | false | true | false | — |
| `tests/test_evidence_intake_handoff.py` | `TEST` | false | true | false | — |
| `tests/test_evidence_intake_page.py` | `TEST` | false | true | false | — |
| `tests/test_evidence_source_registry_migration.py` | `TEST` | false | false | false | `system.evidence_source_registry` |
| `tests/test_export_pressing_curation_packet.py` | `TEST` | false | true | false | — |
| `tests/test_factory_sealed_completeness.py` | `TEST` | false | true | false | — |
| `tests/test_gripsweat_detail_resilience.py` | `TEST` | false | true | false | — |
| `tests/test_gripsweat_probe_import_conflicts.py` | `TEST` | false | true | false | — |
| `tests/test_ingest_assignment_queue_wrapper.py` | `TEST` | false | true | false | `warehouse.auction_pressing_assignment` |
| `tests/test_ingest_new_auctions_product_ui.py` | `TEST` | false | true | false | — |
| `tests/test_latest_refresh_cloud_dispatch.py` | `TEST` | false | true | false | — |
| `tests/test_latest_refresh_ui_source.py` | `TEST` | false | false | false | — |
| `tests/test_live_collector_pagination.py` | `TEST` | false | true | false | — |
| `tests/test_main_review_recent_integration.py` | `TEST` | false | false | false | — |
| `tests/test_marketplace_source_progress.py` | `TEST` | false | false | false | — |
| `tests/test_media_aware_reference.py` | `TEST` | false | true | false | `system.component_type` |
| `tests/test_media_aware_reference_page.py` | `TEST` | false | true | false | — |
| `tests/test_multisource_ingestion_round.py` | `TEST` | false | true | false | — |
| `tests/test_multisource_stable_reference_evidence.py` | `TEST` | false | true | false | `warehouse.auction` |
| `tests/test_new_auction_intake_migration.py` | `TEST` | false | false | false | `system.listing_completeness_snapshot`, `system.new_auction_assignment_queue` |
| `tests/test_new_auction_intake_page.py` | `TEST` | false | true | false | — |
| `tests/test_normalization_readiness.py` | `TEST` | false | false | false | `warehouse.auction_completeness` |
| `tests/test_normalization_verdict_migration.py` | `TEST` | false | false | false | `system.deterministic_verdict_rule`, `system.deterministic_verdict_rule_audit`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation` |
| `tests/test_normalization_verdict_pages.py` | `TEST` | false | true | false | — |
| `tests/test_normalization_workbench.py` | `TEST` | false | false | false | `analytics.normalization_work_queue`, `warehouse.auction_comparable_review` |
| `tests/test_normalization_workbench_migration.py` | `TEST` | false | false | false | `analytics.normalization_work_queue`, `system.normalization_work_audit_event`, `system.normalization_work_batch`, `system.normalization_work_batch_row`, `warehouse.auction_analysis_input`, `warehouse.auction_comparable_review`, `warehouse.auction_condition_normalization` |
| `tests/test_normalization_workbench_page.py` | `TEST` | false | true | false | — |
| `tests/test_on_demand_ingest_colima_runtime.py` | `TEST` | false | false | false | — |
| `tests/test_phase_c_refresh_schema.py` | `TEST` | false | false | false | `ops.refresh_event`, `ops.refresh_job`, `ops.refresh_marketplace` |
| `tests/test_phase_d_auth_contract.py` | `TEST` | false | true | true | — |
| `tests/test_phase_d_documentation.py` | `TEST` | false | false | false | — |
| `tests/test_phase_d_schema_contract.py` | `TEST` | false | false | true | `account.artist_marketplace`, `account.auction_listing`, `account.marketplace_connection`, `account.tracked_artist`, `identity.account`, `identity.account_member`, `identity.app_user` |
| `tests/test_pressing_reference_admin.py` | `TEST` | false | true | false | — |
| `tests/test_pressing_reference_catalog_page.py` | `TEST` | false | false | false | — |
| `tests/test_pressing_reference_domain.py` | `TEST` | false | false | false | — |
| `tests/test_pressing_reference_workbench.py` | `TEST` | false | true | false | — |
| `tests/test_pressing_reference_workbench_page.py` | `TEST` | false | true | false | — |
| `tests/test_recent_ingestion_reporting.py` | `TEST` | false | false | false | — |
| `tests/test_reference_audit_migration.py` | `TEST` | false | false | false | `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.evidence_attachment`, `system.evidence_source_registry`, `system.reference_audit_event`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation` |
| `tests/test_reference_record_admin.py` | `TEST` | false | false | false | `system.bulk_observation_batch`, `system.bulk_observation_batch_row`, `system.evidence_attachment`, `system.reference_audit_event`, `warehouse.auction_component_observation`, `warehouse.pressing_component_expectation` |
| `tests/test_reference_record_admin_page.py` | `TEST` | false | true | false | — |
| `tests/test_refresh_background_progress_contract.py` | `TEST` | false | true | false | — |
| `tests/test_review_and_apply_pressing_packet.py` | `TEST` | false | false | false | `warehouse.component_type` |
| `tests/test_safe_sync_contract.py` | `TEST` | false | true | false | `warehouse.py` |
| `tests/test_staging_database_identity.py` | `TEST` | false | true | false | — |
| `tests/test_state_safe_completeness_and_media_profile_acceptance.py` | `TEST` | false | true | false | — |
| `tests/test_state_safe_completeness_and_media_profile_pages.py` | `TEST` | false | true | false | — |
| `tests/test_state_safe_completeness_and_media_profiles.py` | `TEST` | false | true | false | `system.media_profile_audit_event`, `system.media_profile_component` |
| `tests/test_update_auction_fx_dynamic_verification.py` | `TEST` | false | true | false | — |
| `tests/test_update_auction_fx_staging_identity.py` | `TEST` | false | true | false | — |
| `tests/test_vercel_dependency_surface.py` | `TEST` | false | false | false | — |
| `tests/test_vercel_python_routing.py` | `TEST` | false | false | false | — |
| `tests/test_workspace_ux_v3.py` | `TEST` | false | true | false | — |
| `tests/unit/__init__.py` | `TEST` | false | false | false | — |
| `tests/unit/browser/__init__.py` | `TEST` | false | false | false | — |
| `tests/unit/browser/test_manager.py` | `TEST` | false | false | false | — |
| `tests/unit/browser/test_profiles.py` | `TEST` | false | false | false | — |
| `vercel.json` | `NO_DATABASE_SCOPE_SIGNAL` | false | false | false | — |

## Enforcement gate

Before public multi-user access:

1. convert or explicitly justify every `ACCOUNT_SCOPE_REQUIRED` runtime path;
2. prove owner backfill counts;
3. make refresh create/read/latest account-owned;
4. account-scope collector and workflow writes;
5. restrict shared/global writes to system admins;
6. enable RLS only after code/backfill verification.
