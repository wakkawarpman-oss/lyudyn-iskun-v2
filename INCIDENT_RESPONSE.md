# 🚨 INCIDENT RESPONSE RUNBOOK: Дії при Компрометації

## 1. Сценарій А: Компрометація Токена Оператора
1. Негайно анулювати ключ у Redis:
   ```bash
   redis-cli DEL tactical:approval:<token>:*
   ```
2. Офіцер Безпеки (@btntrx) надсилає команду `/security` в боті для аудиту активних сесій.
3. Перевірити журнал `audit_sec.security_audit_trail` на предмет вивантаження CoT стрімів з невідомих IP.

## 2. Сценарій Б: Компрометація Master TACTICAL_API_TOKEN
1. Згенерувати новий 64-символьний токен: `openssl rand -hex 32`.
2. Оновити `.env` на сервері:
   ```bash
   sed -i "s/TACTICAL_API_TOKEN=.*/TACTICAL_API_TOKEN=<NEW_TOKEN>/" .env
   ```
3. Перестворити контейнер: `docker compose up -d web_api`.
