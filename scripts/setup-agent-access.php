<?php
// Explicit local-only provisioning. No production execution, network calls, or core edits.
require __DIR__ . '/../vendor/autoload.php';
require __DIR__ . '/lib/agent-access.php';
$app = require __DIR__ . '/../bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();

use BookStack\Activity\ActivityType;
use BookStack\Api\ApiToken;
use BookStack\Facades\Activity;
use BookStack\Users\Models\Role;
use BookStack\Users\Models\User;
use BookStack\Users\UserRepo;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Str;
use LookinBase\AgentAccess;

if (config('app.env') !== 'local' || !in_array(config('app.url'), ['http://127.0.0.1:8080', 'http://127.0.0.1:8081'], true)) {
    throw new RuntimeException('Only reviewed local environments are supported');
}
if ($argc !== 2 || $argv[1] !== '--apply') {
    echo json_encode(['mode' => 'preview', 'policies' => AgentAccess::policies(), 'pilot' => 'one synthetic reader, 30-day token; owner role unassigned'], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . PHP_EOL;
    exit;
}
umask(0077);
$private = base_path('local-dev/private/agents');
if (!is_dir($private) && !mkdir($private, 0700, true)) {
    throw new RuntimeException('Cannot create private directory');
}
$file = $private . '/pilot-reader.json';
if (is_link($file)) {
    throw new RuntimeException('Credential symlinks are not supported');
}
$old = is_file($file) ? json_decode(file_get_contents($file), true, 512, JSON_THROW_ON_ERROR) : null;
$email = 'pilot-reader@agents.example.test';
$admin = Role::getSystemRole('admin')->users()->firstOrFail();
auth('standard')->login($admin);
$newSecret = null;
$report = DB::transaction(function () use ($email, $old, &$newSecret) {
    $roles = AgentAccess::ensureRoles();
    $reader = $roles[AgentAccess::READER];
    $writer = $roles[AgentAccess::WRITER];
    if ($writer->users()->exists()) {
        throw new RuntimeException('Reserved owner role unexpectedly assigned');
    }
    $pilot = User::query()->where('email', $email)->first();
    if ($pilot) {
        $ids = $pilot->roles()->pluck('roles.id')->all();
        if ($ids !== [$reader->id] || !$old || $old['user_id'] !== $pilot->id) {
            throw new RuntimeException('Existing pilot identity is not the reviewed reader');
        }
        $token = $pilot->apiTokens()->where('token_id', $old['token_id'])->firstOrFail();
        if (!Hash::check($old['token_secret'], $token->secret) || $token->expires_at->isPast()) {
            throw new RuntimeException('Pilot token invalid or expired; revoke/renew explicitly');
        }
    } else {
        if ($old) {
            throw new RuntimeException('Stale credentials: inspect before provisioning');
        }
        $pilot = app(UserRepo::class)->create([
            'name' => 'ИИ — тестовый читатель', 'email' => $email,
            'password' => Str::random(64), 'roles' => [$reader->id], 'language' => 'ru',
        ]);
        $newSecret = Str::random(48);
        $token = (new ApiToken())->forceFill([
            'user_id' => $pilot->id, 'name' => 'Local pilot — read and export only',
            'token_id' => Str::random(32), 'secret' => Hash::make($newSecret),
            'expires_at' => now()->addDays(30)->format('Y-m-d'),
        ]);
        $token->save();
        Activity::add(ActivityType::API_TOKEN_CREATE, $token);
    }
    $counts = AgentAccess::auditReader($pilot);
    return ['reader_role_id' => $reader->id, 'reserved_owner_role_id' => $writer->id,
        'reserved_owner_role_assigned' => false, 'pilot_user_id' => $pilot->id,
        'pilot_token_id' => $token->id, 'expires_at' => $token->expires_at->format('Y-m-d'),
        'published_content_readable_counts' => $counts, 'effective_content_write_permissions' => false];
});
if ($newSecret !== null) {
    $data = ['base_url' => config('app.url'), 'user_id' => $report['pilot_user_id'],
        'token_id' => ApiToken::findOrFail($report['pilot_token_id'])->token_id,
        'token_secret' => $newSecret, 'expires_at' => $report['expires_at']];
    $stream = fopen($file, 'x');
    if (!$stream) {
        // Avoid leaving a usable credential which the owner cannot retrieve.
        ApiToken::findOrFail($report['pilot_token_id'])->delete();
        throw new RuntimeException('Cannot save new token; token revoked');
    }
    $encoded = json_encode($data, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR) . PHP_EOL;
    if (fwrite($stream, $encoded) !== strlen($encoded)) {
        fclose($stream);
        ApiToken::findOrFail($report['pilot_token_id'])->delete();
        throw new RuntimeException('Cannot fully save new token; token revoked');
    }
    fclose($stream);
    chmod($file, 0600);
}
echo json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . PHP_EOL;
