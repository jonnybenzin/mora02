// Hamburger Menu Toggle
document.addEventListener('DOMContentLoaded', () => {
  const toggle = document.querySelector('.menu-toggle');
  const overlay = document.querySelector('.nav-overlay');

  if (toggle && overlay) {
    toggle.addEventListener('click', () => {
      toggle.classList.toggle('active');
      overlay.classList.toggle('active');
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', !expanded);
      document.body.style.overflow = overlay.classList.contains('active') ? 'hidden' : '';
    });

    // Close on link click
    overlay.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        toggle.classList.remove('active');
        overlay.classList.remove('active');
        toggle.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
      });
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && overlay.classList.contains('active')) {
        toggle.classList.remove('active');
        overlay.classList.remove('active');
        toggle.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
      }
    });
  }
});
