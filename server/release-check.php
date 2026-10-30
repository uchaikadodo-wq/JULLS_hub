<?php
// Run explicitly after restoring the DB and before exposing the site.
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
if (config('app.env') !== 'production' || config('app.debug') || !config('app.key')) {
    throw new RuntimeException('Production environment, disabled debug and preserved APP_KEY are required');
}
$key = config('app.key');
if (!str_starts_with($key, 'base64:') || strlen(base64_decode(substr($key, 7), true) ?: '') !== 32) {
    throw new RuntimeException('APP_KEY must contain a valid 32-byte key; preserve the key belonging to the restored database');
}
if (!in_array(config('app.url'), ['https://base.lookin.team', 'http://127.0.0.1:8082'], true)) {
    throw new RuntimeException('Unexpected application address');
}
$public = (bool) setting('app-public');
$registration = (bool) setting('registration-enabled');
if ($argc === 2 && $argv[1] === '--close-access') {
    setting()->put('app-public', 'false');
    setting()->put('registration-enabled', 'false');
    $public = (bool) setting('app-public');
    $registration = (bool) setting('registration-enabled');
}
if ($public || $registration || config('filesystems.images') !== 'local_secure_restricted') {
    throw new RuntimeException('Require private access, disabled self-registration and restricted image storage');
}
echo json_encode(['private_access' => true, 'self_registration' => false,
    'restricted_images' => true, 'app_env' => config('app.env'), 'debug' => false,
    'php_version' => PHP_VERSION], JSON_PRETTY_PRINT) . PHP_EOL;
