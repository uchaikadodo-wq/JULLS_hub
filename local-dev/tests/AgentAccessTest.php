<?php

namespace Tests\Local;

use BookStack\Api\ApiToken;
use BookStack\Entities\Models\Page;
use BookStack\Uploads\Attachment;
use BookStack\Uploads\AttachmentService;
use Illuminate\Support\Facades\Hash;
use LookinBase\AgentAccess;
use Tests\TestCase;

require_once __DIR__ . '/../../scripts/lib/agent-access.php';

class AgentAccessTest extends TestCase
{
    private array $agentRoles;
    private $reader;
    private $token;
    private array $headers;

    protected function setUp(): void
    {
        parent::setUp();
        $this->assertSame('testing', config('app.env'));
        $this->assertSame('mysql_testing', config('database.default'));
        $this->asAdmin();
        $this->agentRoles = AgentAccess::ensureRoles();
        $this->reader = $this->users->newUser();
        $this->reader->roles()->sync([$this->agentRoles[AgentAccess::READER]->id]);
        $this->token = (new ApiToken())->forceFill([
            'user_id' => $this->reader->id, 'name' => 'synthetic test only',
            'token_id' => 'synthetic-agent-token', 'secret' => Hash::make('synthetic-secret'),
            'expires_at' => now()->addDays(1)->format('Y-m-d'),
        ]);
        $this->token->save();
        $this->headers = ['Authorization' => 'Token synthetic-agent-token:synthetic-secret'];
    }

    private function requestApi(string $method, string $uri, array $data = [])
    {
        auth()->forgetGuards();
        return $this->json($method, '/api/' . $uri, $data, $this->headers);
    }

    public function test_reader_reads_searches_exports_and_downloads_original_attachment(): void
    {
        $page = $this->entities->page();
        foreach (['shelves', 'books', 'chapters', 'pages', 'attachments', 'image-gallery', 'tags/names', 'search?query=test'] as $uri) {
            $this->requestApi('GET', $uri)->assertOk();
        }
        $this->requestApi('GET', 'pages/' . $page->id)->assertOk()->assertJson(['id' => $page->id, 'raw_html' => $page->html]);
        foreach (['html', 'plaintext', 'markdown', 'zip'] as $format) {
            $this->requestApi('GET', "pages/{$page->id}/export/{$format}")->assertOk();
        }
        auth()->forgetGuards();
        $this->asAdmin();
        $attachment = app(AttachmentService::class)->saveNewUpload($this->files->uploadedTextFile('agent-test.txt'), $page->id);
        try {
            $response = $this->requestApi('GET', 'attachments/' . $attachment->id)->assertOk();
            $data = json_decode($response->streamedContent(), true, 512, JSON_THROW_ON_ERROR);
            $this->assertSame(file_get_contents($this->files->testFilePath('test-file.txt')), base64_decode($data['content'], true));
        } finally {
            app(AttachmentService::class)->deleteFile($attachment);
        }
    }

    public function test_reader_cannot_mutate_any_main_content_or_manage_access(): void
    {
        $page = $this->entities->page();
        $book = $page->book;
        $chapter = $this->entities->chapter();
        $shelf = $this->entities->shelf();
        $original = $page->html;
        foreach (['pages' => $page, 'books' => $book, 'chapters' => $chapter, 'shelves' => $shelf] as $kind => $entity) {
            $this->requestApi('POST', $kind, ['name' => 'Forbidden creation', 'book_id' => $book->id, 'html' => '<p>Forbidden content</p>'])->assertForbidden();
            $this->requestApi('PUT', "$kind/{$entity->id}", ['name' => 'Forbidden rename', 'html' => '<p>changed</p>'])->assertForbidden();
            $this->requestApi('DELETE', "$kind/{$entity->id}")->assertForbidden();
        }
        $attachment = Attachment::factory()->create(['uploaded_to' => $page->id, 'external' => true, 'path' => 'https://example.test/file']);
        foreach (['POST' => 'attachments', 'PUT' => 'attachments/' . $attachment->id, 'DELETE' => 'attachments/' . $attachment->id] as $method => $uri) {
            $this->requestApi($method, $uri, ['name' => 'Forbidden', 'uploaded_to' => $page->id, 'link' => 'https://example.test/'])->assertForbidden();
        }
        foreach (['users', 'roles', 'audit-log', 'recycle-bin', 'content-permissions/page/' . $page->id] as $uri) {
            $this->requestApi('GET', $uri)->assertForbidden();
        }
        $this->requestApi('PUT', 'content-permissions/page/' . $page->id, ['owner_id' => $this->reader->id])->assertForbidden();
        $this->requestApi('POST', 'users', ['name' => 'Forbidden'])->assertForbidden();
        $this->requestApi('POST', 'roles', ['display_name' => 'Forbidden'])->assertForbidden();
        $this->requestApi('POST', 'image-gallery')->assertForbidden();
        $this->requestApi('POST', 'comments', ['text' => 'Forbidden', 'page_id' => $page->id])->assertForbidden();
        $this->assertSame($original, $page->fresh()->html);
        $this->assertFalse($page->fresh()->trashed());
    }

    public function test_explicitly_closed_page_is_hidden_from_direct_read_search_and_attachments(): void
    {
        $page = $this->entities->page();
        $attachment = Attachment::factory()->create(['uploaded_to' => $page->id, 'external' => true]);
        $this->permissions->setEntityPermissions($page);
        $this->requestApi('GET', 'pages/' . $page->id)->assertNotFound();
        $this->requestApi('GET', 'pages/' . $page->id . '/export/markdown')->assertNotFound();
        $this->requestApi('GET', 'attachments/' . $attachment->id)->assertNotFound();
        $results = $this->requestApi('GET', 'search?query=' . urlencode($page->name))->assertOk()->json('data');
        foreach ($results as $result) {
            $this->assertFalse($result['type'] === 'page' && $result['id'] === $page->id);
        }
        $this->requestApi('GET', 'pages?filter[id:eq]=' . $page->id)->assertJson(['total' => 0]);
    }

    public function test_revocation_and_expiry_block_token(): void
    {
        $this->requestApi('GET', 'books')->assertOk();
        $this->token->expires_at = now()->subDay()->format('Y-m-d');
        $this->token->save();
        $this->requestApi('GET', 'books')->assertForbidden();
        $this->token->delete();
        $this->requestApi('GET', 'books')->assertUnauthorized();
    }

    public function test_reserved_owner_role_can_edit_with_attributed_revision_but_cannot_delete_or_administer(): void
    {
        $page = $this->entities->page();
        $this->reader->roles()->sync([$this->agentRoles[AgentAccess::WRITER]->id]);
        $this->requestApi('POST', 'pages', ['book_id' => $page->book_id, 'name' => 'Owner agent test', 'html' => '<p>Created</p>'])->assertOk();
        $this->requestApi('PUT', 'pages/' . $page->id, ['html' => '<p>Owner agent update</p>'])->assertOk();
        $this->assertSame($this->reader->id, $page->fresh()->updated_by);
        $this->assertActivityExists('page_update', $page);
        $this->assertTrue($page->revisions()->exists());
        $this->requestApi('DELETE', 'pages/' . $page->id)->assertForbidden();
        $this->requestApi('GET', 'users')->assertForbidden();
        $this->requestApi('PUT', 'content-permissions/page/' . $page->id, [])->assertForbidden();
    }

    public function test_policy_is_repeatable_and_refuses_extra_permissions(): void
    {
        $this->assertSame($this->agentRoles[AgentAccess::READER]->id, AgentAccess::ensureRoles()[AgentAccess::READER]->id);
        $this->agentRoles[AgentAccess::READER]->attachPermission(\BookStack\Permissions\Models\RolePermission::getByName('page-update-all'));
        $this->expectException(\RuntimeException::class);
        AgentAccess::ensureRoles();
    }

    public function test_reader_audit_catches_content_override_granting_write(): void
    {
        $page = $this->entities->page();
        $this->permissions->setEntityPermissionsForRole($page, ['view', 'update'], $this->agentRoles[AgentAccess::READER]);
        $this->expectException(\RuntimeException::class);
        $this->expectExceptionMessage('write access');
        AgentAccess::auditReader($this->reader);
    }
}
