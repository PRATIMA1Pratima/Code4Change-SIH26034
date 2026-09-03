let initialized = false;

function isActive(path) {
  const current = location.pathname;
  return path === '/'
    ? current === '/'
    : current === path || current.startsWith(`${path}/`);
}

function closeMobileMenu() {
  const panel = document.getElementById('mobile-nav');
  const button = document.querySelector('[data-mobile-menu]');
  if (!panel || !button) return;

  panel.hidden = true;
  button.setAttribute('aria-expanded', 'false');
}

function toggleMobileMenu() {
  const panel = document.getElementById('mobile-nav');
  const button = document.querySelector('[data-mobile-menu]');
  if (!panel || !button) return;

  const isOpen = !panel.hidden;
  panel.hidden = isOpen;
  button.setAttribute('aria-expanded', String(!isOpen));
}

export function mobileMenuMarkup() {
  const active = (path) => isActive(path) ? ' class="active"' : '';
  return `<button class="mobile-menu-button" type="button" data-mobile-menu aria-controls="mobile-nav" aria-expanded="false" aria-label="Open navigation menu">⋮</button>
    <div class="mobile-menu" id="mobile-nav" hidden>
      <div class="mobile-menu-heading">Navigate</div>
      <div class="nav mobile-nav" aria-label="Mobile navigation">
        <button data-nav="/"${active('/')} aria-label="Overview"><span class="nav-icon">01</span><span>Overview</span></button>
        <button data-nav="/inspect"${active('/inspect')} aria-label="New inspection"><span class="nav-icon">+</span><span>New inspection</span></button>
        <button data-nav="/history"${active('/history')} aria-label="Inspection history"><span class="nav-icon">≡</span><span>History</span></button>
        <button data-nav="/reports"${active('/reports')} aria-label="Reports"><span class="nav-icon">↗</span><span>Reports</span></button>
        <button data-nav="/analytics"${active('/analytics')} aria-label="Analytics"><span class="nav-icon">∿</span><span>Analytics</span></button>
        <div class="mobile-menu-divider"></div>
        <button data-nav="/rules"${active('/rules')} aria-label="Compliance rules"><span class="nav-icon">□</span><span>Compliance rules</span></button>
        <button data-nav="/help"${active('/help')} aria-label="How it works"><span class="nav-icon">?</span><span>How it works</span></button>
        <button data-nav="/settings"${active('/settings')} aria-label="Settings"><span class="nav-icon">·</span><span>Settings</span></button>
      </div>
    </div>`;
}

export function bindMobileMenu() {
  if (initialized) return;
  initialized = true;

  document.addEventListener('click', (event) => {
    if (event.target.closest('[data-mobile-menu]')) {
      toggleMobileMenu();
      return;
    }

    if (event.target.closest('#mobile-nav [data-nav]')) {
      closeMobileMenu();
      return;
    }

    const panel = document.getElementById('mobile-nav');
    if (panel && !panel.hidden && !event.target.closest('#mobile-nav')) {
      closeMobileMenu();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeMobileMenu();
  });
}