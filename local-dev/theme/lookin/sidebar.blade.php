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
            <a class="lk-nav-item" href="{{ url('/') }}">@icon('contents') Главная</a>
            <a class="lk-nav-item {{ request()->is('books*') ? 'is-active' : '' }}" href="{{ url('/books') }}">@icon('book') Все материалы</a>
            <a class="lk-nav-item {{ request()->is('shelves*') ? 'is-active' : '' }}" href="{{ url('/shelves') }}">@icon('bookshelf') Полки</a>
            <a class="lk-nav-item {{ request()->is('favourites*') ? 'is-active' : '' }}" href="{{ url('/favourites') }}">@icon('star') Избранное</a>
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
