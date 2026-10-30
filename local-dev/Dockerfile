# Local development only. No upstream installer/entrypoint is executed.
FROM composer:2@sha256:b6dcd72ca98fa19d0e5b8476de179859704891fad06dd9e0b96833d4c430a5fc AS composer
FROM php:8.3-cli-bookworm@sha256:cdb77e306d6bb99db40e513fbe036ecc6c53b575cbcb7e581387845fef26d755
RUN apt-get update && apt-get install -y --no-install-recommends \
    git unzip libfreetype6-dev libjpeg62-turbo-dev libpng-dev libzip-dev libldap2-dev \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-configure ldap --with-libdir="lib/$(gcc -dumpmachine)" \
    && docker-php-ext-install -j2 pdo_mysql gd ldap zip bcmath \
    && rm -rf /var/lib/apt/lists/*
COPY --from=composer /usr/bin/composer /usr/local/bin/composer
RUN groupadd -g 1000 developer && useradd -m -u 1000 -g 1000 developer \
    && printf 'memory_limit=512M\nsession.upload_progress.enabled=0\n' > /usr/local/etc/php/conf.d/local-dev.ini
WORKDIR /app
USER 1000:1000
# Fail the build if the pinned PHP image does not meet the reviewed patch level.
RUN php -r 'exit(version_compare(PHP_VERSION, "8.3.36", ">=") ? 0 : 1);'
