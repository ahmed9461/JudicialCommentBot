# نموذج البيانات

## users

- id
- telegram_id UNIQUE
- role: owner | allowed
- is_active
- created_at
- added_by

## subjects

يفضل أن تكون ملفات YAML هي المصدر الأساسي للمعرفة، ويمكن تخزين cache فقط في قاعدة البيانات عند الحاجة.

## cases

- id
- normalized_case_number
- court_name
- normalized_court_name
- judgment_year
- deed_number
- appeal_number
- title
- topic_summary
- created_at

Unique index مبدئي على `(normalized_case_number, normalized_court_name)` عندما تكون البيانات متاحة.

## case_sources

- id
- case_id
- source_type
- source_tier
- source_url
- canonical_url
- origin_type
- source_pdf_sha256
- source_page_start
- source_page_end
- verified_at

## case_usages

- id
- case_id
- subject_slug
- requested_by_user_id
- suitability_score
- selection_mode: auto | user_choice
- used_at

## generations

- id
- case_usage_id
- generation_number
- model_provider
- model_name
- status
- validator_status
- created_at

لا نحفظ ملف DOCX نفسه بعد الإرسال. يمكن حفظ hash أو metadata عند الحاجة للتدقيق.

## search_runs

- id
- subject_slug
- requested_by_user_id
- status
- candidate_count
- selected_case_id nullable
- started_at
- finished_at

## candidate_audit

اختياري لكنه مفيد:

- search_run_id
- candidate_key
- source_url
- score
- rejected_reason
- pdf_status

يساعد في فهم لماذا لم يتم اختيار قضية معينة.
