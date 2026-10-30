# Separate production build. No .env, host dependencies or uploaded data in context.
FROM composer:2@sha256:b6dcd72ca98fa19d0e5b8476de179859704891fad06dd9e0b96833d4c430a5fc AS composer-bin
FROM php:8.3-fpm-bookworm@sha256:a1a4f6f48c2e27f4974ea21459ca6c483bd3d4fbe18579ae61571a78bbe59fff AS php-base
RUN apt-get update && apt-get install -y --no-install-recommends \
    unzip libfreetype6-dev libjpeg62-turbo-dev libpng-dev libzip-dev libldap2-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-configure ldap --with-libdir="lib/$(gcc -dumpmachine)" \
    && docker-php-ext-install -j2 pdo_mysql gd ldap zip bcmath opcache \
    && rm -rf /var/lib/apt/lists/*
RUN php -r 'if (version_compare(PHP_VERSION, "8.3.36", "<")) exit(1); foreach (["curl","dom","fileinfo","gd","mbstring","openssl","pdo_mysql","xml","zip"] as $e) if (!extension_loaded($e)) {fwrite(STDERR, "Missing extension: $e\n"); exit(1);}'
WORKDIR /app

FROM node:24-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS assets
WORKDIR /app
COPY package.json ./
COPY server/dependencies/package-lock.json ./package-lock.json
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY resources ./resources
COPY dev/build ./dev/build
COPY tsconfig.json ./
RUN npm run production && find public/dist -name '*.map' -delete

FROM assets AS js-tests
COPY jest.config.ts ./
CMD ["npm", "run", "test:ci"]

FROM php-base AS dependencies
COPY --from=composer-bin /usr/bin/composer /usr/local/bin/composer
COPY composer.json ./
COPY server/dependencies/composer.lock ./composer.lock
RUN COMPOSER_IPRESOLVE=4 composer install --no-dev --no-plugins --no-scripts --prefer-dist --no-interaction --no-autoloader
COPY app ./app
COPY database ./database
COPY dev/licensing ./dev/licensing
RUN composer dump-autoload --no-dev --no-plugins --no-scripts --optimize
RUN php dev/licensing/gen-php-licenses

FROM php-base AS app
ENV APP_ENV=production APP_DEBUG=false APP_THEME=lookin-base
COPY app ./app
COPY bootstrap/app.php ./bootstrap/app.php
COPY database ./database
COPY lang ./lang
COPY resources ./resources
COPY routes ./routes
COPY public ./public
COPY artisan composer.json LICENSE version ./
COPY server/dependencies/composer.lock ./composer.lock
COPY --from=dependencies /app/vendor ./vendor
COPY --from=assets /app/public/dist ./public/dist
COPY --from=dependencies /app/dev/licensing/php-library-licenses.txt ./dev/licensing/php-library-licenses.txt
COPY dev/licensing/js-library-licenses.txt ./dev/licensing/js-library-licenses.txt
COPY local-dev/theme ./themes/lookin-base
COPY server/php.ini /usr/local/etc/php/conf.d/zz-lookin-production.ini
COPY server/php-fpm.conf /usr/local/etc/php-fpm.d/zz-lookin.conf
COPY server/release-check.php /opt/lookin/release-check.php
RUN mkdir -p storage/app storage/backups storage/fonts/dompdf/cache storage/framework/cache/data \
      storage/framework/sessions storage/framework/views storage/logs storage/uploads/files storage/uploads/images bootstrap/cache public/uploads \
    && chown -R 1000:1000 storage bootstrap/cache public/uploads \
    && rm -f public/web.config \
    && php-fpm -t
USER 1000:1000
CMD ["php-fpm", "-F"]

FROM caddy:2.11.7-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f AS web
COPY --from=app /app/public /srv/public
COPY server/Caddyfile /etc/caddy/Caddyfile
RUN mkdir -p /data/caddy /config/caddy && chown -R 1000:1000 /data /config /srv/public/uploads
USER 1000:1000
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
