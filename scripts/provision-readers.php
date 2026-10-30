<?php

// Run via the production app CLI. Input comes from protected stdin, never argv.
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
require_once __DIR__ . '/lib/agent-access.php';

use BookStack\Users\Models\User;
use BookStack\Users\Models\Role;
use BookStack\Users\UserRepo;
use BookStack\Permissions\PermissionsRepo;
use BookStack\Permissions\Models\RolePermission;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Hash;

try {
    if (config('app.env') !== 'production' || config('app.url') !== 'https://base.lookin.team') {
        throw new RuntimeException('Unexpected target');
    }
    $input = json_decode(stream_get_contents(STDIN, 65536), true, flags: JSON_THROW_ON_ERROR);
    $apply = in_array('--apply', $argv, true);
    $people = $input['people'] ?? [];
    if (!is_array($people) || count($people) < 1 || count($people) > 20) {
        throw new RuntimeException('Invalid batch');
    }
    $actor = User::where('email', $input['actor_email'] ?? '')->firstOrFail();
    if (!$actor->hasSystemRole('admin')) {
        throw new RuntimeException('Expected administrator');
    }
    Auth::setUser($actor);
    $name = 'Коллеги — чтение';
    $expected = ['content-export', 'bookshelf-view-all', 'book-view-all', 'chapter-view-all', 'page-view-all'];
    $roles = Role::where('display_name', $name)->get();
    if ($roles->count() > 1 || RolePermission::whereIn('name', $expected)->count() !== count($expected)) {
        throw new RuntimeException('Ambiguous policy');
    }
    $role = $roles->first();
    if ($role) {
        $actual = $role->permissions()->pluck('name')->all();
        sort($actual); sort($expected);
        if ($actual !== $expected || $role->system_name || $role->entityPermissions()->exists()) {
            throw new RuntimeException('Existing reader policy differs');
        }
    }
    $seen = [];
    foreach ($people as $person) {
        $email = $person['email'] ?? '';
        if (!filter_var($email, FILTER_VALIDATE_EMAIL) || isset($seen[strtolower($email)]) ||
            !is_string($person['name'] ?? null) || mb_strlen($person['name']) < 1 || mb_strlen($person['name']) > 100 ||
            !is_string($person['password'] ?? null) || strlen($person['password']) < 24) {
            throw new RuntimeException('Invalid person data');
        }
        $seen[strtolower($email)] = true;
        $existing = User::whereRaw('LOWER(email) = ?', [strtolower($email)])->first();
        if ($existing && (!$role || $existing->name !== $person['name'] ||
            $existing->roles()->pluck('roles.id')->all() !== [$role->id] ||
            !Hash::check($person['password'], $existing->password))) {
            throw new RuntimeException('Existing account differs; no accounts changed');
        }
    }
    if (!$apply) {
        echo json_encode(['preflight'=>'PASS', 'accounts'=>count($people), 'role_exists'=>(bool)$role]);
        exit;
    }
    $report = DB::transaction(function () use ($people, $role, $name, $expected) {
        if (!$role) {
            $role = app(PermissionsRepo::class)->saveNewRole([
                'display_name'=>$name, 'description'=>'Просмотр, поиск и выгрузка опубликованных материалов. Без API, записи, удаления и управления.',
                'permissions'=>$expected,
            ]);
        }
        $results = [];
        foreach ($people as $person) {
            $user = User::where('email', $person['email'])->first();
            $created = !$user;
            if (!$user) {
                $user = app(UserRepo::class)->create([
                    'name'=>$person['name'], 'email'=>$person['email'], 'password'=>$person['password'],
                    'language'=>'ru', 'roles'=>[$role->id],
                ], false);
            }
            $user = $user->fresh();
            $permissions = $user->roles->flatMap(fn($r)=>$r->permissions->pluck('name'))->unique()->sort()->values()->all();
            $wanted = $expected; sort($wanted);
            if ($permissions !== $wanted || $user->hasSystemRole('admin') || $user->can('access-api')) {
                throw new RuntimeException('Unexpected effective permissions');
            }
            $counts = LookinBase\AgentAccess::auditReader($user);
            $results[] = ['id'=>$user->id, 'created'=>$created, 'read_only_audit'=>'PASS', 'published_entities'=>$counts];
        }
        return ['result'=>'PASS', 'accounts'=>$results, 'api_enabled'=>false, 'emails_sent'=>false];
    });
    echo json_encode($report);
} catch (Throwable $error) {
    // Never echo input or exception details, which could contain personal data.
    fwrite(STDERR, "Reader provisioning stopped; no batch changes committed. Review protected input and policy.\n");
    exit(1);
}
