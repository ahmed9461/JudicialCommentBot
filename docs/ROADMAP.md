# خارطة التنفيذ

## المرحلة 0 — Foundation

- [x] اسم المشروع وقرارات التخطيط وذاكرة المشروع.
- [x] سياسة المصادر وPDF وStyle Guide ومخطط البيانات.
- [x] ملفات معرفة جميع المواد مستقلة.
- [ ] مراجعة خرائط المعرفة دورياً مقابل توصيفات المقررات الرسمية وتوثيقها.

## المرحلة 1 — Bot Shell & Auth

- [x] Telegram bot + Owner/Allowlist + أزرار المواد + SQLite + Logging + CI.

## المرحلة 2 — Research & Sources

- [x] Research provider وDeepSeek Responses API والبحث الويب والـstructured candidates.
- [x] source registry وسياسة trusted domains وإرسال سجل الاستبعاد.
- [ ] اختبار تكامل حي بمفتاح DeepSeek حقيقي في بيئة المستخدم.

## المرحلة 3 — PDF Acquisition

- [x] تنزيل PDF رسمي، SSRF/redirect protections، validation، SHA-256.
- [x] اكتشاف صفحات القضية داخل مجموعة رسمية عند توفر رقم قضية قابل للتحقق.
- [x] استخراج original page objects والتحقق من رقم القضية بعد الاستخراج.
- [x] retry/fallback بين المرشحين.

## المرحلة 4 — Ranking & Deduplication

- [x] scoring engine بأوزان 40/20/15/15/10.
- [x] auto-select threshold + margin وإلا top-3.
- [x] duplicate detection قبل الإرسال برقم القضية+المحكمة أو SHA-256.
- [x] قاعدة بيانات وسجل إداري.

## المرحلة 5 — Commentary & DOCX

- [x] استخراج نص الحكم من PDF المتحقق.
- [x] structured commentary generation.
- [x] DOCX RTL مع عناوين متكيفة حسب المادة وترقيم صفحات.
- [x] إعادة توليد التعليق.

## المرحلة 6 — Validation & Cleanup

- [x] Validators للنص وDOCX وPDF.
- [x] إرسال PDF + DOCX ثم تسجيل القضية.
- [x] حذف الملفات بعد الإرسال وstale cleanup.
- [x] Admin history وaudit log.

## المرحلة 7 — Tests & Hardening

- [x] اختبارات Authorization/Knowledge/PDF/Source policy/Ranking/Validation/Dedup/Cleanup.
- [x] CI للتثبيت والتجميع والاختبارات.
- [ ] Smoke test حي كامل مع Telegram + DeepSeek + قضية رسمية في بيئة المستخدم.

## المرحلة 8 — Deployment

- [x] Dockerfile + Docker Compose.
- [x] systemd service.
- [x] health check.
- [x] SQLite backup script + systemd timer.
- [x] log rotation policy وتوثيق التحديث والرجوع.

## شرط الإطلاق

الشفرة جاهزة للإطلاق بعد نجاح CI. المتبقي خارج المستودع هو وضع أسرار المستخدم في `.env` ثم إجراء Smoke test حي واحد قبل الاعتماد التشغيلي.
