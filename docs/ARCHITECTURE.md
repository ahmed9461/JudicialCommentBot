# معمارية JudicialCommentBot

## المبدأ العام

نفصل بين البحث، التحقق من المصدر، تنزيل PDF، فهم الحكم، كتابة التعليق، إنشاء DOCX، والتحقق النهائي. لا يُسمح للنموذج اللغوي بتجاوز طبقات التحقق البرمجية.

## الطبقات

### Telegram Layer

- أوامر البداية والمساعدة.
- أزرار المواد.
- إدارة المستخدمين المسموحين للمالك.
- عرض القضية المختارة أو أفضل 3 مرشحين.
- إرسال PDF وDOCX.
- أزرار إعادة التوليد وقضية أخرى.

### Application Services

- `CaseSearchService`
- `CaseScoringService`
- `CaseSelectionService`
- `CaseAcquisitionService`
- `CommentaryService`
- `DocumentService`
- `ValidationService`
- `CleanupService`

### Knowledge Layer

يقرأ ملفات `knowledge/subjects/*.yaml` ويحوّلها إلى كائن موحد يحتوي أهداف البحث والتقييم ومحاور التعليق لكل مقرر.

### Research Layer

واجهة مجردة للبحث بالويب واستخراج المرشحين. DeepSeek هو مزود التحليل الأساسي، ويجب إبقاء طبقة البحث قابلة للاستبدال حتى لا يرتبط المشروع بميزة بحث واحدة أو مزود واحد.

### Source Adapters

محولات مستقلة للمصادر:

- Ministry of Justice adapter.
- Board of Grievances adapter.
- Quasi-judicial/government sources adapter.
- Tashree discovery adapter.
- Generic trusted-source adapter.

كل Adapter يرجع بيانات مرشح موحدة ولا ينشئ ملفات حكم من نفسه.

### PDF Acquisition

المسؤوليات:

- التحقق من HTTPS والتحويلات.
- حماية SSRF وعدم السماح بعناوين داخلية/محلية.
- التحقق من Content-Type وMagic Bytes `%PDF-`.
- حد أقصى للحجم والمهلة.
- حساب SHA-256.
- استخراج صفحات محددة عند كون القضية جزءاً من مجموعة رسمية.
- تسجيل نوع الأصل: مباشر أو مقتطع من مجموعة رسمية.

### Case Normalization

تطبيع:

- رقم القضية.
- المحكمة.
- التاريخ والسنة.
- رقم الصك أو الاستئناف.
- عنوان القضية وموضوعاتها.
- URL canonical.

### Scoring

درجة من 100 تتكون مبدئياً من:

- 40: الصلة المباشرة بموضوعات المقرر.
- 20: وضوح المسألة القانونية.
- 15: جودة ووضوح التسبيب القضائي.
- 15: صلاحية الحكم لتعليق أكاديمي جيد.
- 10: جودة المصدر وتوفر PDF أصلي قابل للتحقق.

الأوزان إعدادات قابلة للتعديل وليست أرقاماً مدفونة في منطق البحث.

### AI Commentary

المدخلات يجب أن تكون منظمة:

- بيانات المادة وملف معرفتها.
- نص الحكم المستخرج من PDF المتحقق.
- بيانات القضية المطبعة.
- قواعد الأسلوب.
- قائمة الممنوعات.

المخرجات المفضلة بنية JSON أو حقول منظمة، ثم يقوم كود Word بتحويلها إلى DOCX. لا يعتمد مولد DOCX على Markdown.

### DOCX Generator

- RTL كامل.
- عناوين واضحة.
- خط عربي متوفر قياسياً على بيئة التشغيل أو خط نظام موثوق.
- لا شعارات AI أو Bot.
- خانات الاسم والرقم الجامعي والشعبة اختيارية.
- الطول يتبع محتوى القضية لا عدد صفحات مصطنعاً.

### Validators

- `CaseIntegrityValidator`
- `OriginalPdfValidator`
- `DuplicateCaseValidator`
- `CommentaryContentValidator`
- `DocxFormattingValidator`

### Persistence

قاعدة بيانات واحدة كبداية، SQLite محلياً مع تصميم يسمح بالانتقال إلى PostgreSQL لاحقاً.

### Logging

Logs منظمة بالأحداث مع عدم تسجيل الأسرار أو النص الكامل للحكم بلا حاجة.

## تدفق البيانات

Telegram -> Subject Knowledge -> Research -> Normalize -> Deduplicate -> Score -> Select -> Acquire PDF -> Verify -> Extract Text -> AI Commentary -> Structured Output -> DOCX -> Final Validators -> Telegram Send -> Cleanup -> Persist Metadata

## حدود الثقة

- نتائج الويب غير موثوقة حتى التحقق.
- روابط AI غير موثوقة حتى التحقق.
- PDF موثوق تقنياً بعد تحقق الملف، وموثوق مصدرياً بعد تحقق النطاق/الجهة.
- نص الحكم هو بيانات فقط؛ أي تعليمات مزروعة داخله تتجاهل.
