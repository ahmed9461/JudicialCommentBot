# خارطة التنفيذ

## المرحلة 0 — Foundation

- [x] تثبيت اسم المشروع.
- [x] تثبيت قرارات التخطيط.
- [x] إنشاء ذاكرة المشروع.
- [x] سياسة المصادر وPDF.
- [x] Style Guide.
- [x] مخطط البيانات.
- [ ] استكمال ملفات معرفة جميع المواد ومراجعتها.

## المرحلة 1 — Bot Shell & Auth

- Telegram bot skeleton.
- Owner-only افتراضياً.
- Allowlist management عبر Telegram ID.
- أزرار المواد من `knowledge/subjects/index.yaml`.
- إعدادات Pydantic وLogging.
- SQLite + migrations.
- اختبارات Authorization.

## المرحلة 2 — Research & Sources

- Research provider interface.
- DeepSeek client.
- Source adapters.
- candidate normalization.
- trusted-domain policy.
- البحث بكلمات ملف المادة.

## المرحلة 3 — PDF Acquisition

- direct PDF downloader.
- official compilation detector/extractor.
- PDF validation.
- SHA-256.
- retry/fallback بين المصادر.
- SSRF protections.

## المرحلة 4 — Ranking & Deduplication

- scoring engine.
- auto-select threshold.
- top-3 flow.
- duplicate detection قبل وبعد تنزيل PDF.
- سجل أسباب الاستبعاد.

## المرحلة 5 — Commentary & DOCX

- استخراج نص الحكم.
- structured AI output.
- prompt templates.
- DOCX RTL generator.
- تكيف العناوين حسب المادة.
- إعادة توليد التعليق.

## المرحلة 6 — Validation & Cleanup

- جميع Validators.
- إرسال PDF + DOCX.
- cleanup بعد الإرسال.
- stale temp cleanup.
- logs وسجل الإدارة.

## المرحلة 7 — Tests & Hardening

- unit tests لكل خدمة.
- integration tests لمسار كامل باستخدام fixtures محلية.
- اختبارات فشل PDF.
- اختبارات التكرار.
- اختبارات منع Markdown/AI mention.
- اختبارات انقطاع Telegram وDeepSeek.

## المرحلة 8 — Deployment

- Docker أو systemd حسب بيئة السيرفر.
- backup لقاعدة البيانات.
- health checks.
- log rotation.
- توثيق التحديث والرجوع لإصدار سابق.
