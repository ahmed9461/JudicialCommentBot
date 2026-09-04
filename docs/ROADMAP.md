# خارطة التنفيذ

## المرحلة 0 — Foundation

- [x] تثبيت اسم المشروع.
- [x] تثبيت قرارات التخطيط.
- [x] إنشاء ذاكرة المشروع.
- [x] سياسة المصادر وPDF.
- [x] Style Guide.
- [x] مخطط البيانات.
- [x] إنشاء ملفات معرفة جميع المواد كملفات مستقلة.
- [ ] مراجعة خرائط المعرفة مقابل توصيفات المقررات الرسمية وتوثيق مصادرها.

## المرحلة 1 — Bot Shell & Auth

- [x] Telegram bot skeleton.
- [x] Owner-only افتراضياً.
- [x] Allowlist management عبر Telegram ID.
- [x] أزرار المواد من `knowledge/subjects/index.yaml`.
- [x] إعدادات Pydantic وLogging.
- [x] SQLite + migrations.
- [x] اختبارات Authorization وKnowledge loading.
- [x] CI أولي للتجميع والاختبارات.

## المرحلة 2 — Research & Sources

- [x] Research provider interface.
- [x] DeepSeek Responses API client.
- [x] DeepSeek server-side web search integration.
- [x] candidate normalization إلى نموذج موحد.
- [x] trusted-domain/source registry policy.
- [x] بناء طلب البحث من ملف معرفة المادة.
- [x] إرسال سجل القضايا السابقة كقائمة استبعاد للبحث.
- [ ] Source adapters متخصصة عند الحاجة للمصادر التي تتطلب parsing مخصص.
- [ ] اختبار تكامل حي بمفتاح DeepSeek حقيقي.

## المرحلة 3 — PDF Acquisition

- [x] direct PDF downloader للمصادر الرسمية المعتمدة.
- [ ] official compilation detector وتحديد صفحات القضية تلقائياً.
- [x] أداة استخراج page range من ملف مجموعة رسمي مع الحفاظ على صفحات الحكم.
- [x] PDF magic + structural validation.
- [x] SHA-256 أثناء التنزيل.
- [ ] retry/fallback بين عدة مرشحين داخل orchestrator.
- [x] HTTPS/domain/DNS SSRF protections مع إعادة فحص كل redirect.

## المرحلة 4 — Ranking & Deduplication

- [ ] scoring engine.
- [ ] auto-select threshold.
- [ ] top-3 flow.
- [ ] duplicate detection قبل وبعد تنزيل PDF.
- [ ] سجل أسباب الاستبعاد.

## المرحلة 5 — Commentary & DOCX

- [ ] استخراج نص الحكم.
- [ ] structured AI output.
- [ ] prompt templates.
- [ ] DOCX RTL generator.
- [ ] تكيف العناوين حسب المادة.
- [ ] إعادة توليد التعليق.

## المرحلة 6 — Validation & Cleanup

- [ ] جميع Validators.
- [ ] إرسال PDF + DOCX.
- [ ] cleanup بعد الإرسال.
- [ ] stale temp cleanup.
- [ ] logs وسجل الإدارة.

## المرحلة 7 — Tests & Hardening

- [ ] unit tests لكل خدمة.
- [ ] integration tests لمسار كامل باستخدام fixtures محلية.
- [x] اختبارات PDF validation وSSRF الأساسية.
- [ ] اختبارات فشل PDF عبر الشبكة.
- [ ] اختبارات التكرار.
- [ ] اختبارات منع Markdown/AI mention.
- [ ] اختبارات انقطاع Telegram وDeepSeek.

## المرحلة 8 — Deployment

- [ ] Docker أو systemd حسب بيئة السيرفر.
- [ ] backup لقاعدة البيانات.
- [ ] health checks.
- [ ] log rotation.
- [ ] توثيق التحديث والرجوع لإصدار سابق.
