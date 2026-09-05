-- MineIQ deterministic synthetic demo/test fixture.
-- This data is synthetic and is not official CIL data.
-- Idempotent: safe to execute repeatedly.

BEGIN;

-- Base source documents used by graph, PQ, RAG numeric and discrepancy tests.
INSERT INTO documents
    (id, original_filename, s3_key, source_type, idempotency_key, status,
     doc_type, subsidiary, urgency, extracted_text, uploaded_by)
VALUES
('11111111-1111-4111-8111-111111111111',
 'MCL_annual_report_2025_fixture.csv',
 'fixture/MCL_annual_report_2025_fixture.csv',
 'spreadsheet', 'mineiq-fixture-mcl-annual-2025', 'classified',
 'Annual Production Report', 'MCL', 'medium',
 'Synthetic MCL 2025 production report: Lakhanpur Open Cast Mine; Ananta Colliery; Kulda Mine.',
 'mineiq-fixture'),

('22222222-2222-4222-8222-222222222222',
 'MCL_comparison_report_2025_fixture.csv',
 'fixture/MCL_comparison_report_2025_fixture.csv',
 'spreadsheet', 'mineiq-fixture-mcl-comparison-2025', 'classified',
 'Production Comparison Report', 'MCL', 'high',
 'Synthetic comparison report for MCL 2025. Kulda Mine actual production is reported as 21.0 MT.',
 'mineiq-fixture'),

('33333333-3333-4333-8333-333333333333',
 'NCL_production_2025_fixture.csv',
 'fixture/NCL_production_2025_fixture.csv',
 'spreadsheet', 'mineiq-fixture-ncl-2025', 'classified',
 'Annual Production Report', 'NCL', 'medium',
 'Synthetic NCL 2025 production report for Singrauli Mine.',
 'mineiq-fixture'),

('44444444-4444-4444-8444-444444444444',
 'SECL_production_2024_fixture.csv',
 'fixture/SECL_production_2024_fixture.csv',
 'spreadsheet', 'mineiq-fixture-secl-2024', 'classified',
 'Annual Production Report', 'SECL', 'medium',
 'Synthetic SECL 2024 production report for Gevra and Dipka mines.',
 'mineiq-fixture')
ON CONFLICT (idempotency_key) DO UPDATE SET
  original_filename=EXCLUDED.original_filename,
  s3_key=EXCLUDED.s3_key,
  source_type=EXCLUDED.source_type,
  status=EXCLUDED.status,
  doc_type=EXCLUDED.doc_type,
  subsidiary=EXCLUDED.subsidiary,
  urgency=EXCLUDED.urgency,
  extracted_text=EXCLUDED.extracted_text,
  uploaded_by=EXCLUDED.uploaded_by,
  updated_at=CURRENT_TIMESTAMP;

DELETE FROM structured_data
WHERE document_id IN (
 '11111111-1111-4111-8111-111111111111',
 '22222222-2222-4222-8222-222222222222',
 '33333333-3333-4333-8333-333333333333',
 '44444444-4444-4444-8444-444444444444'
);

INSERT INTO structured_data
    (document_id, mine_name, subsidiary, report_year,
     production_target_mt, actual_production_mt, dispatch_mt, overburden_mcum, raw_json)
VALUES
('11111111-1111-4111-8111-111111111111','Lakhanpur Open Cast Mine','MCL',2025,56.0,54.1,51.2,12.4,
 '{"fixture":true,"source":"MCL_annual_report_2025_fixture.csv"}'),
('11111111-1111-4111-8111-111111111111','Ananta Colliery','MCL',2025,30.0,28.5,27.0,8.1,
 '{"fixture":true,"source":"MCL_annual_report_2025_fixture.csv"}'),
('11111111-1111-4111-8111-111111111111','Kulda Mine','MCL',2025,20.0,19.2,18.5,5.2,
 '{"fixture":true,"source":"MCL_annual_report_2025_fixture.csv"}'),

-- Same fact tuple in a second document, intentionally different to exercise discrepancy detection.
('22222222-2222-4222-8222-222222222222','Kulda Mine','MCL',2025,20.0,21.0,18.5,5.2,
 '{"fixture":true,"source":"MCL_comparison_report_2025_fixture.csv","intentionally_conflicting":true}'),

('33333333-3333-4333-8333-333333333333','Singrauli Mine','NCL',2025,70.0,67.4,65.1,14.0,
 '{"fixture":true,"source":"NCL_production_2025_fixture.csv"}'),

('44444444-4444-4444-8444-444444444444','Gevra Mine','SECL',2024,80.0,77.5,74.8,16.2,
 '{"fixture":true,"source":"SECL_production_2024_fixture.csv"}'),
('44444444-4444-4444-8444-444444444444','Dipka Mine','SECL',2024,55.0,52.7,50.4,11.3,
 '{"fixture":true,"source":"SECL_production_2024_fixture.csv"}');

COMMIT;
