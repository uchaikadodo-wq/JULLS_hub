<?php
// Restrict only the reviewed local environment; no credentials/roles/content are changed.
require __DIR__ . '/../vendor/autoload.php';
$app = require __DIR__ . '/../bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
if (config('app.env') !== 'local' || config('app.url') !== 'http://127.0.0.1:8080') {
    throw new RuntimeException('Only the reviewed local environment is supported.');
}
$before = ['public_access' => (bool) setting('app-public'), 'self_registration' => (bool) setting('registration-enabled')];
setting()->put('app-public', 'false');
setting()->put('registration-enabled', 'false');
echo json_encode(['before' => $before, 'after' => ['public_access' => (bool) setting('app-public'), 'self_registration' => (bool) setting('registration-enabled')], 'image_storage' => config('filesystems.images'), 'upload_max_filesize' => ini_get('upload_max_filesize'), 'post_max_size' => ini_get('post_max_size'), 'app_key_changed' => false], JSON_PRETTY_PRINT) . PHP_EOL;
