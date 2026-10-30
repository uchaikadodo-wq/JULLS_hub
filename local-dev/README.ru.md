# BookStack: локальная разработка на Mac

Подготовлено 26.10.2026. Папка проекта до работы была пуста. Все файлы находятся в `bookstack-local/`.

**Статус 26.10.2026: локальная система запущена и проверена.** Docker Desktop 4.97.0, Engine 29.9.2, Compose 5.6.1. Сборка, установка зависимостей, platform requirements, миграции и вход синтетическим администратором прошли. Приложение и БД изолированы; web-посредник публикует только `127.0.0.1:8080`. PHP 8.3.36, upload progress отключён. PHP test suite пока не запускался; старые npm audit findings остаются неисправленными. Доказательства: `runtime-checks.json`, `http-checks.json`, `startup.log`, `docker-build.log`.

**Первый вход:** http://127.0.0.1:8080, логин `local-admin@example.test`, пароль в защищённом локальном файле `local-dev/private/login.txt` (0600, исключён из Git). Стандартный admin@admin.com/password заменён.

Если команда `docker` не найдена в Terminal: `export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"`. PHP и Composer на Mac не устанавливались; они работают внутри контейнера.

**Особенность Docker Desktop:** прямое опубликование app из internal-сети в проверенной среде не обеспечивало доступ с Mac, хотя внутри контейнера HTTP работал. Добавлен `web`: небольшой HTTP-посредник на уже закреплённом Node-образе, только с одним read-only скриптом, без .env и кода приложения. Он связан с ingress и isolated сетями и передаёт запросы только в app:8080. Сам app, БД и инструменты node остаются только в isolated-сети. Посредник имеет обычную ingress-сеть и потенциальный внешний доступ; отсутствие внешнего доступа проверяется именно для app, а не обещается для посредника. Причина поведения Desktop отдельно не доказана; корректность обходного варианта проверена HTTP-входом.

## Зафиксированная база

- Официальная инструкция: https://www.bookstackapp.com/docs/admin/installation/ — адрес клонирования `https://source.bookstackapp.com/bookstack.git` (теперь Codeberg).
- Получен тег `v26.09.2`, tag object `2491f40de31d297189f1d15aa35362914e5f6d9c`.
- Commit `6265d5667dd6904b7aa0d05a8c60795cf104011b`.
- Ветка для изменений: `local/bookstack-dev`; origin оставлен официальным upstream.
- Clone shallow, только выбранный тег. Для просмотра более ранней истории: `git fetch --unshallow origin`.
- Подпись тега присутствует, но локально НЕ проверена: `git verify-tag v26.09.2` завершился ошибкой отсутствия GPG. HTTPS и совпадение SHA не заменяют криптографическую проверку подписи.
- Образы PHP, Composer, MySQL и Node закреплены multi-platform SHA256 digest; `images.json` сохраняет платформы. Для linux/arm64 PHP_VERSION=8.3.36 подтверждён метаданными registry (`php-image-metadata.json`), выполнение PHP ещё не проверено. APT-пакеты не закреплены по версиям: полная побитовая воспроизводимость сборки не обещается.

## Первый запуск (после установки Docker)

Команды выполнять последовательно в Terminal. Не запускайте штатный `docker-compose.yml` или скрипты `dev/docker/`. Во всех командах явно указан безопасный compose-файл. `.env` также задаёт `COMPOSE_FILE=compose.local.yaml` для защиты от случайного запуска штатной конфигурации.

```sh
cd '/Users/juliaseagull/Documents/ChatGPT/База знаний лт/bookstack-local'
docker version
docker compose version
docker compose -f compose.local.yaml config --quiet
docker compose -f compose.local.yaml build app
```

`.env` уже создан с синтетическими значениями, уникальным случайным APP_KEY и правами 0600; он исключён из Git. Если после клонирования своего Git-репозитория `.env` отсутствует, создайте его командой `python3 local-dev/prepare-env.py`. Скрипт откажется перезаписывать существующий файл.

Установка зависимостей — отдельный явный шаг с доступом к сети; lifecycle scripts и Composer plugins отключены. `composer.lock` и `package-lock.json` используются без обновления версий. Контейнеры установки видят только эту папку; не кладите в неё реальные секреты. Если ранее использовали npm на Mac, следующий `npm ci` заменит `node_modules` на Linux-версию. При возвращении к запуску npm на Mac снова выполните локальный `npm ci --ignore-scripts`.

```sh
docker compose -f compose.local.yaml run --rm --no-deps php-deps
docker compose -f compose.local.yaml run --rm --no-deps node-deps
docker compose -f compose.local.yaml up -d --wait db
docker compose -f compose.local.yaml run --rm --no-deps app composer check-platform-reqs
docker compose -f compose.local.yaml run --rm --no-deps app php artisan package:discover --ansi
docker compose -f compose.local.yaml run --rm --no-deps app php artisan migrate --database=mysql --no-interaction
# Only on a NEW installation: generate credentials and replace the untouched default admin.
python3 local-dev/prepare-admin.py
docker compose -f compose.local.yaml run --rm --no-deps app php local-dev/bootstrap-admin.php
docker compose -f compose.local.yaml run --rm --no-deps node npm run build
docker compose -f compose.local.yaml up -d app web
docker compose -f compose.local.yaml ps
curl --fail --silent --show-error -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/login
```

Откройте http://127.0.0.1:8080. После описанной первичной настройки используется `local-admin@example.test`, пароль — в `local-dev/private/login.txt`. Генератор не перезаписывает существующие файлы; bootstrap откажется менять учётную запись, если стандартный пароль уже заменён. Создавайте только вымышленные книги/страницы. Почта пишется в локальный log (`MAIL_DRIVER=log`), реального SMTP нет. Логи могут содержать текст тестовых писем и ссылки сброса пароля; не переносите их на сервер.

Проверка ограничения сети и версии PHP после старта:

```sh
docker compose -f compose.local.yaml port web 8080
docker compose -f compose.local.yaml port db 3306
docker compose -f compose.local.yaml exec app php -v
docker compose -f compose.local.yaml exec app php -r 'echo ini_get("session.upload_progress.enabled"), PHP_EOL;'
docker network inspect bookstack-local_isolated --format '{{.Internal}}'
```

Первая команда должна показать `127.0.0.1:8080`; для базы порт отсутствует (возможен ненулевой exit code). PHP должен быть >=8.3.36 в ветке 8.3, upload progress выключен, Internal=true. Если запуск не прошёл, смотрите `docker compose -f compose.local.yaml logs --tail=100 app db`. Не исправляйте это публикацией 3306, подключением host network или запуском от root. PHP встроенный сервер выбран только для dev, не для production. Совместимость образов, расширений, Docker bind mounts и internal-сети с конкретной версией Docker Desktop должна быть подтверждена этим первым запуском.

## Работа с кодом и тесты

Редактируйте `app/`, `resources/`, `routes/`, `tests/` непосредственно в этой папке через Codex. Bind mount ограничен этой папкой. Для JS/CSS после правок выполняйте `npm run build` в контейнере node; PHP перечитывается при запросе. Команда `npm run dev`/watch намеренно не используется: штатный esbuild watch поднимает дополнительный HTTP-сервер и CORS `*`.

Тестовая БД `bookstack-test` отделена от dev-БД схемой; оба содержат только синтетические данные. Подготовка один раз на новый volume:

```sh
docker compose -f compose.local.yaml run --rm --no-deps app php artisan migrate --database=mysql_testing --no-interaction
docker compose -f compose.local.yaml run --rm --no-deps app php artisan db:seed --class=DummyContentSeeder --database=mysql_testing --no-interaction
```

Повторный seed на существующую тестовую БД может создать дубликаты; не выполняйте его перед каждым тестом. Seeder создаёт фиктивные сущности и тестовый API-токен, не запускайте его на production.

```sh
docker compose -f compose.local.yaml run --rm --no-deps app php vendor/bin/phpunit
docker compose -f compose.local.yaml run --rm --no-deps app composer lint
docker compose -f compose.local.yaml run --rm --no-deps app composer check-static
docker compose -f compose.local.yaml run --rm --no-deps node npm run test:ci
docker compose -f compose.local.yaml run --rm --no-deps node npm run lint
docker compose -f compose.local.yaml run --rm --no-deps node npm run ts:lint
docker compose -f compose.local.yaml run --rm --no-deps node npm run production
```

Composer check-static может потребовать больше памяти для крупных изменений. PHP platform requirements проверены; PHPUnit/lint/static ещё не запускались. Для сетевых тестов, если такие появятся, сначала изучите конкретный тест: runtime изолирован от внешней сети намеренно. Обновлённый аудит требует download-сети:

```sh
docker compose -f compose.local.yaml run --rm --no-deps php-deps composer audit --locked --no-plugins
docker compose -f compose.local.yaml run --rm --no-deps node-deps npm audit --package-lock-only --ignore-scripts
```

## Остановка и повторный запуск

```sh
docker compose -f compose.local.yaml stop
docker compose -f compose.local.yaml start
# Либо удалить контейнеры/сеть с сохранением данных базы:
docker compose -f compose.local.yaml down
# После down:
docker compose -f compose.local.yaml up -d --wait db
docker compose -f compose.local.yaml up -d app web
```

`down` сохраняет volume базы и файлы в bind mount. `down --volumes` удалит локальную БД; это отдельное разрушительное действие, не часть обычной остановки. Состояние приложения (storage/uploads/cache) находится в этой папке, в личные каталоги ничего не монтируется.

## Перенос собственных изменений через Git

Ничего на сервер не отправлено и не развёрнуто. Сначала исправьте/оцените найденные npm vulnerabilities и добейтесь прохождения PHP/runtime-проверок. Версия BookStack и PHP на сервере неизвестна; сравните их с этой базой. Обновление схемы требует отдельной проверки и резервной копии.

1. Создайте свой PRIVATE Git-репозиторий, сохраните upstream в origin, добавьте свой remote с именем `personal`. Не используйте токены в URL remote. Например, после подстановки своего реального SSH URL:

```sh
git remote add personal git@YOUR_GIT_HOST:YOUR_ACCOUNT/bookstack.git
git remote -v
git status --short
git diff --check
git diff
```

2. Добавляйте конкретные файлы. Для инфраструктуры этого окружения: `.dockerignore compose.local.yaml local-dev/`. Для собственных правок — только реально изменённые файлы app/resources/routes/tests и, если меняли JS/CSS, необходимые `public/dist/*` после production-сборки. Не используйте `git add .` вслепую. Не добавляйте `.env`, vendor, node_modules, storage, uploads, логи, дампы или тестовые данные. `git check-ignore .env vendor node_modules` проверяет исключения.

3. Просмотрите `git diff --cached --stat`, `git diff --cached`, затем выполните commit. Эти команды здесь не выполнялись:

```sh
git commit -m 'Describe the reviewed BookStack changes'
git push -u personal local/bookstack-dev
```

Первый push из shallow clone может не поддерживаться пустым Git-сервером: тогда сначала `git fetch --unshallow origin` и повторите push. Не переписывайте историю upstream force-push.

4. На сервере отдельно, после backup БД, `.env`, uploads и storage: fetch из personal и ревью конкретного SHA. Применяйте свои commits на совместимую версию BookStack или выбирайте проверенный release branch своего fork. Не копируйте dev Compose и локальную `.env` в production. Production сохраняет собственный APP_KEY, БД, секреты и SMTP. Используйте обычный серверный web stack, composer install --no-dev и production-ассеты по регламенту сервера, затем отдельно одобренные миграции и smoke-test. Эти действия не выполнялись; команды деплоя зависят от ещё неизвестного устройства сервера.

Rollback кода не откатывает миграции и содержимое БД: нужен заранее проверенный backup/restore. Данные и файлы приложения не передаются через Git.

## Результаты и файлы

См. `SECURITY.ru.md`, `verification.json`, сохранённые audit JSON и test logs. `FILES.txt` содержит полный список созданных файлов, включая исходники, `.git`, зависимости и временные sourcemaps внутри проекта; `SOURCE-FILES.txt` — перечень 2622 upstream-файлов на зафиксированном теге. `node_modules` и vendor не предназначены для Git. Сборка проверена, затем семь изменённых ею tracked `public/dist/*` восстановлены до исходного release; новые sourcemaps остаются ignored.

## Повторная проверка работающего окружения

```sh
python3 local-dev/check-runtime.py
python3 local-dev/check-http.py
```

Первая команда проверяет контейнеры и один исходящий TCP-запрос из app, вторая — страницу входа и вход созданным локальным администратором. Пароли/cookies не печатаются. Если пароль изменён через интерфейс, проверка входа с прежним локальным файлом ожидаемо не пройдёт. `verification.json` сохраняет первоначальный отчёт до установки Docker; текущее состояние — в `runtime-verification.json`.
