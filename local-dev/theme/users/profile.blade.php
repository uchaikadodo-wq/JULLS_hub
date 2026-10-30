@extends('layouts.simple')
@section('body')
<div class="lk-profile container">
    <div class="lk-page-heading"><span class="lk-overline">КОМАНДА / ПРОФИЛЬ</span><h1>{{ user()->id === $user->id ? 'Мой профиль' : 'Профиль участника' }}</h1><p>Личное пространство и вклад в общие знания.</p></div>
    <section class="lk-profile-hero" aria-labelledby="profile-name">
        <div class="lk-profile-avatar" aria-hidden="true">@if($user->avatar()->exists())<img src="{{ $user->getAvatar(120) }}" alt="">@else{{ mb_substr($user->name, 0, 1) }}@endif</div>
        <div class="lk-profile-identity"><span class="lk-overline">УЧАСТНИК LOOKIN.TEAM BASE</span><h2 id="profile-name">{{ $user->name }}</h2><p>{{ trans('entities.profile_user_for_x', ['time' => $dates->relative($user->created_at, false)]) }}</p></div>
        @if(user()->id === $user->id)<a class="button outline lk-profile-edit" href="{{ url('/my-account/profile') }}">@icon('edit') Редактировать профиль</a>@endif
    </section>
    <section class="lk-profile-counts" aria-label="Созданные материалы">
        @foreach([['pages', 'Страницы', 'page'], ['chapters', 'Главы', 'chapter'], ['books', 'Книги', 'book'], ['shelves', 'Полки', 'bookshelf']] as [$key, $label, $icon])
            <div class="lk-stat"><span class="lk-stat-icon">@icon($icon)</span><strong>{{ $assetCounts[$key] }}</strong><span>{{ $label }}</span></div>
        @endforeach
    </section>
    <div class="lk-profile-grid">
        <section class="card content-wrap lk-profile-materials">
            <div class="lk-panel-heading"><span class="lk-overline">МОЙ ВКЛАД</span><h2>{{ user()->id === $user->id ? 'Созданные материалы' : 'Материалы участника' }}</h2></div>
            @if(collect($recentlyCreated)->sum(fn($items) => count($items)) === 0)
                <div class="lk-empty-state"><span class="lk-empty-icon">@icon('book')</span><h3>Здесь появятся материалы</h3><p>{{ user()->id === $user->id ? 'Ваши страницы, главы и книги соберутся здесь. Начните с просмотра базы и найдите своё направление.' : 'Участник пока не создавал материалы в базе.' }}</p><a class="button" href="{{ url('/books') }}">Открыть базу знаний @icon('chevron-right')</a></div>
            @else
                @foreach(['pages' => 'Страницы', 'chapters' => 'Главы', 'books' => 'Книги', 'shelves' => 'Полки'] as $type => $label)
                    @if(count($recentlyCreated[$type]) > 0)
                        <h3>{{ $label }}</h3>
                        @include('entities.list', ['entities' => $recentlyCreated[$type], 'showPath' => true])
                    @endif
                @endforeach
            @endif
        </section>
        <section class="card content-wrap lk-profile-activity"><div class="lk-panel-heading"><span class="lk-overline">ИСТОРИЯ</span><h2>Недавние действия</h2></div>@include('common.activity-list', ['activity' => $activity])</section>
    </div>
</div>
@stop
