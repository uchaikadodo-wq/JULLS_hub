<?php
// Only for an isolated local release check. Never run against the working database.
require '/app/vendor/autoload.php';
$app = require '/app/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
if (config('app.env') !== 'production' || config('app.url') !== 'http://127.0.0.1:8082') {
    throw new RuntimeException('Only isolated local release verification is allowed');
}
$admin = \BookStack\Users\Models\Role::getSystemRole('admin')->users()->firstOrFail();
$password = bin2hex(random_bytes(24));
$admin->email = 'release-admin@example.test';
$admin->password = \Illuminate\Support\Facades\Hash::make($password);
$admin->save();
auth()->login($admin);
setting()->put('app-name', 'Lookin.Team Base');
setting()->put('app-public', 'false');
setting()->put('registration-enabled', 'false');
$role = app(\BookStack\Permissions\PermissionsRepo::class)->saveNewRole([
    'display_name' => 'Synthetic release reader',
    'permissions' => ['access-api', 'content-export', 'bookshelf-view-all', 'book-view-all', 'chapter-view-all', 'page-view-all'],
]);
$reader = app(\BookStack\Users\UserRepo::class)->create([
    'name' => 'Synthetic reader', 'email' => 'release-reader@example.test', 'roles' => [$role->id],
]);
$secret = bin2hex(random_bytes(24));
$token = (new \BookStack\Api\ApiToken())->forceFill([
    'name' => 'Synthetic release check', 'user_id' => $reader->id, 'token_id' => bin2hex(random_bytes(16)),
    'secret' => \Illuminate\Support\Facades\Hash::make($secret), 'expires_at' => now()->addDay()->format('Y-m-d'),
]);
$token->save();
$book = app(\BookStack\Entities\Repos\BookRepo::class)->create(['name' => 'Юридическое — тест']);
$pageRepo = app(\BookStack\Entities\Repos\PageRepo::class);
$page = $pageRepo->getNewDraftPage($book);
$pageRepo->publishDraft($page, ['name' => 'Тестовая инструкция', 'html' => '<p>Синтетические данные для проверки переноса.</p>']);
$file = tmpfile();
fwrite($file, "Lookin release synthetic attachment\n");
$upload = new \Illuminate\Http\UploadedFile(stream_get_meta_data($file)['uri'], 'release-test.txt', 'text/plain', null, true);
$attachment = app(\BookStack\Uploads\AttachmentService::class)->saveNewUpload($upload, $page->id);
echo json_encode(['admin_email' => $admin->email, 'admin_password' => $password,
    'token_id' => $token->token_id, 'token_secret' => $secret,
    'book_id' => $book->id, 'page_id' => $page->id, 'page_url' => $page->getUrl(),
    'attachment_id' => $attachment->id], JSON_THROW_ON_ERROR);
