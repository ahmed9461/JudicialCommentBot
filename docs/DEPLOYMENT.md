# النشر والتشغيل

## المتطلبات

- Python 3.12+ أو Docker حديث.
- متغيرات البيئة في `.env` محلي على الخادم، ولا يُرفع الملف إلى Git.
- القيم الإلزامية للتشغيل الحقيقي: `TELEGRAM_BOT_TOKEN` و`OWNER_TELEGRAM_ID` و`DEEPSEEK_API_KEY`.
- في النشر الجديد يجب بناء الفهرس القضائي الرسمي مرة واحدة قبل استخدام البحث من Telegram.

## تشغيل محلي للاختبار

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# عبّئ الأسرار في .env
python -m app.catalog refresh
python -m app.catalog stats
python -m app
```

قبل التشغيل يمكن تنفيذ:

```bash
python -m compileall -q app
pytest -q
```

## Docker Compose

```bash
cp .env.example .env
# عبّئ الأسرار

docker compose up -d --build
docker compose ps
docker compose logs -f bot
```

قاعدة البيانات والملفات التشغيلية في volume باسم `runtime_data`. الـPDF والـDOCX ملفات مؤقتة ويحذفها التطبيق بعد الإرسال، وتوجد عملية تنظيف للملفات المتروكة من تشغيل متقطع.

نسخة احتياطية يدوية داخل الحاوية:

```bash
docker compose exec bot python scripts/backup_db.py
```

## systemd

المسار المقترح `/opt/JudicialCommentBot` والمستخدم `judicialbot`:

```bash
sudo useradd --system --home /opt/JudicialCommentBot --shell /usr/sbin/nologin judicialbot || true
sudo chown -R judicialbot:judicialbot /opt/JudicialCommentBot
cd /opt/JudicialCommentBot
sudo -u judicialbot python3.12 -m venv .venv
sudo -u judicialbot .venv/bin/pip install .
sudo -u judicialbot mkdir -p runtime/tmp runtime/backups
sudo cp deploy/judicial-comment-bot.service /etc/systemd/system/
sudo cp deploy/judicial-comment-bot-backup.service /etc/systemd/system/
sudo cp deploy/judicial-comment-bot-backup.timer /etc/systemd/system/
sudo cp deploy/judicial-comment-bot-catalog.service /etc/systemd/system/
sudo cp deploy/judicial-comment-bot-catalog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now judicial-comment-bot.service
sudo systemctl enable --now judicial-comment-bot-backup.timer
sudo systemctl enable --now judicial-comment-bot-catalog.timer
```

### أول بناء للفهرس الرسمي

الفهرسة عملية صيانة منفصلة عن Telegram لأنها قد تنزل مجموعات أحكام كبيرة. نفذها مرة واحدة بعد النشر:

```bash
sudo systemctl start judicial-comment-bot-catalog.service
```

راقبها من نافذة أخرى:

```bash
sudo journalctl -u judicial-comment-bot-catalog -f
```

ثم تحقق:

```bash
sudo -u judicialbot /opt/JudicialCommentBot/.venv/bin/python -m app.catalog stats
```

التحديث الأسبوعي بعد ذلك incremental؛ الملفات الرسمية المسجلة سابقاً تُتجاوز ولا يعاد تنزيل الأرشيف كله. عند تعديل خوارزمية استخراج القضايا عمداً يمكن إعادة البناء باستخدام:

```bash
sudo -u judicialbot /opt/JudicialCommentBot/.venv/bin/python -m app.catalog refresh --force
```

## الفحص

```bash
sudo systemctl status judicial-comment-bot
sudo journalctl -u judicial-comment-bot -f
sudo -u judicialbot /opt/JudicialCommentBot/.venv/bin/python -m app.healthcheck
sudo -u judicialbot /opt/JudicialCommentBot/.venv/bin/python -m app.catalog stats
```

ومن Telegram يستطيع المالك استخدام `/catalog` لعرض حجم الفهرس.

## التحديث

1. خذ نسخة احتياطية قبل التحديث.
2. اسحب التغييرات.
3. أعد تثبيت الحزمة لأن الاعتمادات قد تتغير.
4. حدّث ملفات systemd عند وجود تغييرات نشر.
5. شغّل الاختبارات.
6. أعد تشغيل البوت وشغّل تحديث الفهرس بشكل مستقل.

```bash
sudo -u judicialbot .venv/bin/python scripts/backup_db.py
sudo -u judicialbot git pull --ff-only
sudo -u judicialbot .venv/bin/pip install .
sudo cp deploy/judicial-comment-bot-catalog.service /etc/systemd/system/
sudo cp deploy/judicial-comment-bot-catalog.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now judicial-comment-bot-catalog.timer
sudo -u judicialbot .venv/bin/pytest -q
sudo systemctl restart judicial-comment-bot
```

## الرجوع لإصدار سابق

احتفظ بمعرّف Commit معروف أنه سليم. عند الحاجة:

```bash
git log --oneline -20
sudo systemctl stop judicial-comment-bot
sudo -u judicialbot git checkout <GOOD_COMMIT>
sudo -u judicialbot .venv/bin/pip install .
sudo systemctl start judicial-comment-bot
```

بعد تشخيص المشكلة ارجع إلى `main` بالطريقة المعتادة. لا تستبدل قاعدة البيانات بنسخة قديمة إلا إذا كان ذلك مطلوباً فعلاً؛ احتفظ بالنسخ الاحتياطية منفصلة.

## السجلات

التطبيق يكتب إلى stdout/stderr. مع systemd تُدار السجلات بواسطة journald. مع Docker تم ضبط تدوير سجلات `json-file` في `compose.yaml` حتى لا تنمو بلا حد.
