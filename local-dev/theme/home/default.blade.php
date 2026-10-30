@extends('layouts.base')
@push('body-class')
lookin-home
@endpush
@push('head')
<link rel="stylesheet" href="{{ url('/theme/lookin-base/lookin.css') }}?v=3">
@endpush
@section('content')
<div class="lk-shell">
    <aside class="lk-sidebar" aria-label="Навигация по базе">
        <a class="lk-brand" href="{{ url('/') }}" aria-label="Lookin.Team Base — главная">
            <span class="lk-mark" aria-hidden="true">L<span>.</span></span>
            <span>lookin<span class="lk-brand-dot">.</span>team<small>БАЗА ЗНАНИЙ</small></span>
        </a>
        <a class="lk-person" aria-label="Мой профиль" href="{{ user()->getProfileUrl() }}">
            <span class="lk-avatar" aria-hidden="true">{{ mb_substr(user()->name, 0, 1) }}</span>
            <span class="lk-person-label">{{ user()->name }}<small>Мой профиль</small></span>
            <span class="lk-arrow" aria-hidden="true">↗</span>
        </a>
        <nav class="lk-nav" aria-label="Основная навигация">
            <a class="lk-nav-item is-active" href="{{ url('/') }}" aria-current="page">@icon('contents') Главная</a>
            <a class="lk-nav-item" href="{{ url('/books') }}">@icon('book') Все материалы</a>
            <a class="lk-nav-item" href="{{ url('/favourites') }}">@icon('star') Избранное</a>
        </nav>
        <div class="lk-nav-label">НАПРАВЛЕНИЯ</div>
        <nav class="lk-directions" aria-label="Поиск по направлениям">
            @php
                $lookinNavBooks = app(\BookStack\Entities\Queries\EntityQueries::class)->books->visibleForList()->orderBy('name')->limit(12)->get();
            @endphp
            @foreach($lookinNavBooks as $lookinNavItem)
                <a href="{{ $lookinNavItem->getUrl() }}" title="Открыть раздел: {{ $lookinNavItem->name }}"><span>@icon('book')</span>{{ $lookinNavItem->name }}<span class="lk-direction-arrow" aria-hidden="true">↗</span></a>
            @endforeach
            @foreach([
                ['HR и команда', 'HR', '01'],
                ['Маркетинг', 'маркетинг', '02'],
                ['IT и сервисы', 'IT', '03'],
                ['Операционная работа', 'операции', '04'],
                ['Финансы', 'финансы', '05'],
                ['Развитие', 'развитие', '06'],
            ] as [$label, $term, $number])
                <a href="{{ url('/search') }}?{{ http_build_query(['term' => $term]) }}" title="Найти материалы: {{ $label }}"><span>{{ $number }}</span>{{ $label }}<span class="lk-direction-arrow" aria-hidden="true">↗</span></a>
            @endforeach
        </nav>
        <div class="lk-sidebar-bottom">
            <a class="lk-nav-item" href="{{ url('/my-account') }}">@icon('user-preferences') Моя учётная запись</a>
            @if(userCan('settings-manage'))
                <a class="lk-nav-item" href="{{ url('/settings') }}">@icon('settings') Настройки базы</a>
            @endif
            <div class="lk-sidebar-note"><span aria-hidden="true"></span> Пространство знаний команды</div>
        </div>
    </aside>
    <main class="lk-main" id="main-content">
        <div class="lk-topline"><span>LOOKIN.TEAM / БАЗА ЗНАНИЙ</span><a href="{{ url('/books') }}">Открыть материалы <span aria-hidden="true">↗</span></a></div>
        <section class="lk-hero" aria-labelledby="lk-title">
            <div class="lk-eyebrow"><span></span> ЗНАНИЯ, КОТОРЫЕ ПОМОГАЮТ В РАБОТЕ</div>
            <h1 id="lk-title">Всё важное.<br><span>В одном месте.</span></h1>
            <p>Инструкции, ответы и опыт команды — рядом, когда нужны.</p>
            <form class="lk-search" action="{{ url('/search') }}" method="get" role="search">
                <label class="lk-visually-hidden" for="lk-search-input">Поиск по базе знаний</label>
                @icon('search')
                <input id="lk-search-input" type="search" name="term" placeholder="Что хотите найти?" required autocomplete="off">
                <button type="submit" aria-label="Найти в базе">Найти <span aria-hidden="true">↗</span></button>
            </form>
            <div class="lk-suggestions"><span>Например:</span>
                <a href="{{ url('/search') }}?term={{ urlencode('отпуск') }}">оформить отпуск</a>
                <a href="{{ url('/search') }}?term={{ urlencode('брендбук') }}">найти брендбук</a>
                <a href="{{ url('/search') }}?term={{ urlencode('доступ') }}">получить доступ</a>
            </div>
        </section>
        <section class="lk-feed" aria-labelledby="lk-feed-title">
            <div class="lk-feed-heading"><div><span class="lk-section-kicker">ДЕРЖИМ В КУРСЕ</span><h2 id="lk-feed-title">Жизнь команды</h2></div><span class="lk-preview-badge">Демонстрационная лента</span></div>
            <div class="lk-feed-controls" role="group" aria-label="Фильтр демонстрационных новостей">
                <button class="is-active" type="button" data-lk-filter="all" aria-pressed="true">Всё</button>
                <button type="button" data-lk-filter="news" aria-pressed="false">Новости</button>
                <button type="button" data-lk-filter="updates" aria-pressed="false">Обновления базы</button>
                <span>Новости Lookin.Team подключим отдельно</span>
            </div>
            <div class="lk-cards">
                <article class="lk-card lk-feature" data-lk-kind="news">
                    <div class="lk-card-art" aria-hidden="true"><div class="lk-art-orbit"></div><span class="lk-art-tag">LOOKIN.TEAM BASE</span><div class="lk-art-title">Знания работают,<br>когда ими <em>делятся.</em></div><span class="lk-art-plus">+</span></div>
                    <div class="lk-card-content"><div class="lk-card-meta"><span class="lk-tag">Новости команды</span><span>Пример оформления</span></div><h3>Общее пространство для большого опыта</h3><p>Здесь могут появляться новости команды, важные объявления и изменения в работе. Пока это пример будущей ленты.</p><a class="lk-card-link" href="{{ url('/books') }}">Перейти к материалам <span aria-hidden="true">↗</span></a></div>
                </article>
                <article class="lk-card lk-update" data-lk-kind="updates"><div class="lk-card-content"><div class="lk-card-meta"><span class="lk-tag lk-tag-purple">Обновления базы</span><span>Пример оформления</span></div><h3>Нужная инструкция — в нескольких словах от вас</h3><p>Поиск уже работает по доступным вам материалам BookStack. Когда в базе появятся инструкции, их можно будет находить по названию и содержимому.</p><a class="lk-card-link" href="{{ url('/search') }}">Открыть поиск <span aria-hidden="true">↗</span></a></div><div class="lk-update-symbol" aria-hidden="true">↗</div></article>
            </div>
            <p class="lk-feed-note">Названия направлений предварительные. Пока ссылки слева ищут материалы по теме; отдельные разделы настроим после согласования структуры.</p>
        </section>
        <footer class="lk-footer"><span>Lookin.Team Base</span><span>Общий опыт. Понятные ответы.</span></footer>
    </main>
</div>
@endsection
@push('body-end')
<script type="module" src="{{ url('/theme/lookin-base/lookin.js') }}?v=1" nonce="{{ $cspNonce }}"></script>
@endpush
