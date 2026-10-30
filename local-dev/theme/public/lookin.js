// Local UI only; no API calls, analytics, storage or external requests.
const filters = document.querySelectorAll('[data-lk-filter]');
const cards = document.querySelectorAll('[data-lk-kind]');
for (const button of filters) {
    button.addEventListener('click', () => {
        const filter = button.dataset.lkFilter;
        for (const item of filters) {
            const active = item === button;
            item.classList.toggle('is-active', active);
            item.setAttribute('aria-pressed', String(active));
        }
        for (const card of cards) {
            card.hidden = filter !== 'all' && card.dataset.lkKind !== filter;
        }
    });
}
