<?php

// Local integration policy; no changes to BookStack core.
namespace LookinBase;

use BookStack\Permissions\PermissionsRepo;
use BookStack\Permissions\Models\RolePermission;
use BookStack\Users\Models\Role;
use BookStack\Users\Models\User;
use BookStack\Permissions\PermissionApplicator;

final class AgentAccess
{
    public const READER = 'ИИ — чтение и выгрузка';
    public const WRITER = 'ИИ владельца — работа с материалами';

    public static function policies(): array
    {
        $read = ['access-api', 'content-export', 'revision-view-all',
            'bookshelf-view-all', 'book-view-all', 'chapter-view-all', 'page-view-all'];
        return [
            self::READER => ['description' => 'Сторонние агенты: чтение, поиск, выгрузка. Без изменения содержимого и управления системой.', 'permissions' => $read],
            self::WRITER => ['description' => 'Резерв для агентов владельца: чтение, создание и изменение материалов. Без удаления, управления доступом и сервером. Пока никому не назначать.',
                'permissions' => array_merge($read, [
                    'bookshelf-create-all', 'bookshelf-update-all', 'book-create-all', 'book-update-all',
                    'chapter-create-all', 'chapter-update-all', 'page-create-all', 'page-update-all',
                    'attachment-create-all', 'attachment-update-all', 'image-create-all', 'image-update-all', 'editor-change',
                ])],
        ];
    }

    // Refuse unexpected existing roles, rather than silently broadening/changing them.
    public static function ensureRoles(): array
    {
        $roles = [];
        foreach (self::policies() as $name => $data) {
            $expected = $data['permissions'];
            if (RolePermission::query()->whereIn('name', $expected)->count() !== count($expected)) {
                throw new \RuntimeException('Unknown permission in agent policy');
            }
            $matches = Role::query()->where('display_name', $name)->get();
            if ($matches->count() > 1) {
                throw new \RuntimeException('Ambiguous agent role');
            }
            $role = $matches->first();
            if (!$role) {
                $role = app(PermissionsRepo::class)->saveNewRole(array_merge($data, ['display_name' => $name]));
            }
            $actual = $role->permissions()->pluck('name')->all();
            sort($expected);
            sort($actual);
            if ($actual !== $expected || $role->system_name || $role->entityPermissions()->exists()) {
                throw new \RuntimeException('Existing agent role differs from reviewed policy');
            }
            $roles[$name] = $role;
        }
        return $roles;
    }

    public static function auditReader(User $reader): array
    {
        $applicator = new PermissionApplicator($reader);
        $counts = [];
        foreach ([\BookStack\Entities\Models\Bookshelf::class, \BookStack\Entities\Models\Book::class,
            \BookStack\Entities\Models\Chapter::class, \BookStack\Entities\Models\Page::class] as $class) {
            $count = 0;
            foreach ($class::query()->cursor() as $entity) {
                if (!($entity instanceof \BookStack\Entities\Models\Page && $entity->draft)) {
                    if (!$applicator->checkOwnableUserAccess($entity, 'view')) {
                        throw new \RuntimeException('Some published content is closed to this reader; review its permissions explicitly');
                    }
                    $count++;
                }
                foreach (['create', 'update', 'delete'] as $action) {
                    if ($applicator->checkOwnableUserAccess($entity, $action)) {
                        throw new \RuntimeException('Content overrides grant write access to reader; provisioning aborted');
                    }
                }
            }
            $counts[(new $class())->getMorphClass()] = $count;
        }
        return $counts;
    }
}
